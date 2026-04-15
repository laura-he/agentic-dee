"""
MCP DEE Execution Server for Agentic-DEE experiments.

Exposes one tool:
  - run_dee : run a DEE+packing experiment with a given parameter config,
              returns metrics, and auto-logs the result via the logging server.

Parameter space the agent can explore:
  - ex1              (bool) : extra chi1 rotamer samples
  - ex2              (bool) : extra chi2 rotamer samples
  - ex1aro           (bool) : extra chi1 samples for aromatics
  - use_input_sc     (bool) : include input sidechain as rotamer candidate
  - designable_region (str) : 'all', 'core', or 'surface'

PyRosetta is initialized once at module load to avoid re-init overhead.
"""

import json
import os
import time
from pathlib import Path

import pyrosetta
from pyrosetta import pose_from_pdb
from pyrosetta.rosetta.core.pack.task import TaskFactory
from pyrosetta.rosetta.core.pack.task.operation import (
    InitializeFromCommandline,
    OperateOnResidueSubset,
    PreventRepackingRLT,
)
from pyrosetta.rosetta.core.select.residue_selector import (
    LayerSelector,
)
from pyrosetta.rosetta.protocols.minimization_packing import PackRotamersMover

import mcp.server.stdio
import mcp.types as types
from mcp.server import Server

# ---------------------------------------------------------------------------
# PyRosetta init — done once at import time, silent to keep logs clean
# ---------------------------------------------------------------------------
pyrosetta.init(options="-constant_seed", silent=True)

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
PDB_DIR = Path(os.environ.get("DEE_PDB_DIR", "data/pdbs"))
LOG_FILE = Path(os.environ.get("DEE_LOG_FILE", "data/logs/experiments.jsonl"))
LOG_FILE.parent.mkdir(parents=True, exist_ok=True)

SUPPORTED_PROTEINS = ["1VII", "1PGB", "1L2Y"]

# ---------------------------------------------------------------------------
# Logging helper (duplicated from logging_server to keep servers independent)
# ---------------------------------------------------------------------------
def _log_run(record: dict) -> None:
    with open(LOG_FILE, "a") as f:
        f.write(json.dumps(record) + "\n")


# ---------------------------------------------------------------------------
# Core DEE execution logic
# ---------------------------------------------------------------------------
def run_dee_experiment(
    protein: str,
    ex1: bool,
    ex2: bool,
    ex1aro: bool,
    use_input_sc: bool,
    designable_region: str,
) -> dict:
    """
    Run a DEE+packing experiment with the given parameter configuration.
    Returns a metrics dict.
    """
    pdb_path = PDB_DIR / f"{protein}.pdb"
    if not pdb_path.exists():
        raise FileNotFoundError(f"PDB file not found: {pdb_path}")

    # -- Build init flags string from parameters --
    flags = []
    if ex1:
        flags.append("-ex1")
    if ex2:
        flags.append("-ex2")
    if ex1aro:
        flags.append("-ex1aro")
    if use_input_sc:
        flags.append("-use_input_sc")

    # PyRosetta can only be initialized once per process, so we pass rotamer
    # sampling flags via the packer task's ExtraRotamersGeneric operation
    # instead of re-calling pyrosetta.init().
    scorefxn = pyrosetta.create_score_function("ref2015")

    pose = pose_from_pdb(str(pdb_path))
    initial_score = scorefxn(pose)

    # -- Packer task --
    task_factory = TaskFactory()
    task_factory.push_back(InitializeFromCommandline())

    # Apply extra rotamer sampling via ExtraRotamersGeneric
    extra_rot_op = pyrosetta.rosetta.core.pack.task.operation.ExtraRotamersGeneric()
    extra_rot_op.ex1(ex1)
    extra_rot_op.ex2(ex2)
    extra_rot_op.ex1aro(ex1aro)
    task_factory.push_back(extra_rot_op)

    if use_input_sc:
        task_factory.push_back(
            pyrosetta.rosetta.core.pack.task.operation.IncludeCurrent()
        )

    # Restrict designable region if needed
    if designable_region in ("core", "surface"):
        layer_selector = LayerSelector()
        if designable_region == "core":
            layer_selector.set_layers(
                pick_core=True, pick_boundary=False, pick_surface=False
            )
        else:  # surface
            layer_selector.set_layers(
                pick_core=False, pick_boundary=False, pick_surface=True
            )
        # Prevent repacking on residues NOT in the selected layer
        prevent_op = OperateOnResidueSubset(
            PreventRepackingRLT(),
            layer_selector,
            flip_subset=True,  # apply to residues NOT selected
        )
        task_factory.push_back(prevent_op)

    packer_task = task_factory.create_task_and_apply_taskoperations(pose)

    # -- Count rotamers before DEE --
    rotamer_sets = pyrosetta.rosetta.core.pack.rotamer_set.RotamerSets()
    packer_graph = pyrosetta.rosetta.core.pack.create_packer_graph(
        pose, scorefxn, packer_task
    )
    rotamer_sets.set_task(packer_task)
    rotamer_sets.initialize_pose_for_rotsets_creation(pose)
    rotamer_sets.build_rotamers(pose, scorefxn, packer_graph)

    rotamers_pre_dee = sum(
        rotamer_sets.rotamer_set_for_residue(i).num_rotamers()
        for i in range(1, pose.total_residue() + 1)
        if packer_task.being_packed(i)
    )

    # -- Run DEE + packing --
    pack_mover = PackRotamersMover(scorefxn, packer_task)
    start = time.time()
    pack_mover.apply(pose)
    elapsed = time.time() - start

    final_score = scorefxn(pose)

    return {
        "protein": protein,
        "n_residues": pose.total_residue(),
        "initial_score": round(initial_score, 3),
        "final_score": round(final_score, 3),
        "score_improvement": round(initial_score - final_score, 3),
        "rotamers_pre_dee": rotamers_pre_dee,
        "runtime_seconds": round(elapsed, 2),
        "designable_residues": packer_task.num_to_be_packed(),
    }


# ---------------------------------------------------------------------------
# MCP server
# ---------------------------------------------------------------------------
server = Server("dee-execution-server")


@server.list_tools()
async def list_tools() -> list[types.Tool]:
    return [
        types.Tool(
            name="run_dee",
            description=(
                "Run a Dead-End Elimination (DEE) + packing experiment on a "
                "fixed-backbone protein structure with a given parameter "
                "configuration. Returns pruning metrics, energy scores, and "
                "runtime. Results are automatically logged."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "protein": {
                        "type": "string",
                        "enum": SUPPORTED_PROTEINS,
                        "description": "PDB ID of the protein to design.",
                    },
                    "ex1": {
                        "type": "boolean",
                        "description": (
                            "Sample extra chi1 rotamers (±1 SD). "
                            "Increases rotamer count, improves coverage, "
                            "increases runtime. Dahiyat & Mayo 1997 used False."
                        ),
                        "default": False,
                    },
                    "ex2": {
                        "type": "boolean",
                        "description": (
                            "Sample extra chi2 rotamers (±1 SD). "
                            "Further increases rotamer count beyond ex1. "
                            "Dahiyat & Mayo 1997 used False."
                        ),
                        "default": False,
                    },
                    "ex1aro": {
                        "type": "boolean",
                        "description": (
                            "Sample extra chi1 rotamers specifically for "
                            "aromatic residues (Phe, Tyr, Trp, His). "
                            "Useful when aromatic packing is important."
                        ),
                        "default": False,
                    },
                    "use_input_sc": {
                        "type": "boolean",
                        "description": (
                            "Include the input structure's sidechain conformation "
                            "as an additional rotamer candidate. Can improve "
                            "scores when input structure is high quality."
                        ),
                        "default": False,
                    },
                    "designable_region": {
                        "type": "string",
                        "enum": ["all", "core", "surface"],
                        "description": (
                            "Which residues to include in the design. "
                            "'all': every residue (largest search space). "
                            "'core': buried residues only (faster, focuses on "
                            "hydrophobic packing as in Dahiyat & Mayo). "
                            "'surface': exposed residues only."
                        ),
                        "default": "all",
                    },
                    "rationale": {
                        "type": "string",
                        "description": (
                            "Your explanation for why you chose these parameters "
                            "and what you expect to observe. This is logged with "
                            "the results for later analysis."
                        ),
                    },
                },
                "required": ["protein", "rationale"],
            },
        )
    ]


@server.call_tool()
async def call_tool(name: str, arguments: dict) -> list[types.TextContent]:
    if name != "run_dee":
        raise ValueError(f"Unknown tool: {name}")

    protein = arguments["protein"]
    ex1 = arguments.get("ex1", False)
    ex2 = arguments.get("ex2", False)
    ex1aro = arguments.get("ex1aro", False)
    use_input_sc = arguments.get("use_input_sc", False)
    designable_region = arguments.get("designable_region", "all")
    rationale = arguments.get("rationale", "")

    try:
        metrics = run_dee_experiment(
            protein=protein,
            ex1=ex1,
            ex2=ex2,
            ex1aro=ex1aro,
            use_input_sc=use_input_sc,
            designable_region=designable_region,
        )
    except Exception as e:
        return [types.TextContent(
            type="text",
            text=json.dumps({"error": str(e)}),
        )]

    # Auto-log the result
    from datetime import datetime
    record = {
        "id": f"run_{datetime.utcnow().strftime('%Y%m%d_%H%M%S_%f')}",
        "timestamp": datetime.utcnow().isoformat(),
        "protein": protein,
        "parameters": {
            "ex1": ex1,
            "ex2": ex2,
            "ex1aro": ex1aro,
            "use_input_sc": use_input_sc,
            "designable_region": designable_region,
        },
        "metrics": metrics,
        "rationale": rationale,
        "run_type": "agent",
    }
    _log_run(record)

    return [types.TextContent(
        type="text",
        text=json.dumps({
            "run_id": record["id"],
            "metrics": metrics,
            "parameters": record["parameters"],
        }, indent=2),
    )]


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    import asyncio
    asyncio.run(mcp.server.stdio.run(server))