"""
Agentic-DEE Orchestrator

Runs Claude as an agent that autonomously explores the DEE parameter space.
The agent has access to two tools:
  - run_dee        (from dee_server.py)    : execute a DEE experiment
  - get_experiments (from logging_server.py): review past results
  - get_summary    (from logging_server.py): get aggregate stats

The agent runs for a fixed number of iterations, choosing parameters,
executing runs, and reasoning about results each step.

Usage:
    export ANTHROPIC_API_KEY=your_key_here
    python agent.py --protein 1VII --iterations 10
"""

import argparse
import json
import os
import sys
from pathlib import Path

import anthropic

# ---------------------------------------------------------------------------
# Import server logic directly (no subprocess needed — we call functions
# directly rather than running the MCP servers as separate processes)
# ---------------------------------------------------------------------------
sys.path.insert(0, str(Path(__file__).parent / "servers"))
from servers.dee_server import run_dee_experiment, SUPPORTED_PROTEINS
from servers.logging_server import _load_all, _append
from datetime import datetime, UTC

# ---------------------------------------------------------------------------
# Tool definitions (mirrors what the MCP servers expose, but called directly)
# ---------------------------------------------------------------------------
TOOLS = [
    {
        "name": "run_dee",
        "description": (
            "Run a Dead-End Elimination (DEE) + packing experiment on a "
            "fixed-backbone protein structure with a given parameter configuration. "
            "Returns pruning metrics, energy scores, and runtime. "
            "Results are automatically logged."
        ),
        "input_schema": {
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
                        "Sample extra chi1 rotamers (+/-1 SD). "
                        "Increases rotamer count and runtime. "
                        "Dahiyat & Mayo 1997 used False."
                    ),
                },
                "ex2": {
                    "type": "boolean",
                    "description": (
                        "Sample extra chi2 rotamers (+/-1 SD). "
                        "Further increases rotamer count beyond ex1. "
                        "Dahiyat & Mayo 1997 used False."
                    ),
                },
                "ex1aro": {
                    "type": "boolean",
                    "description": (
                        "Sample extra chi1 rotamers for aromatic residues. "
                        "Useful when aromatic packing is important."
                    ),
                },
                "use_input_sc": {
                    "type": "boolean",
                    "description": (
                        "Include the input sidechain conformation as a rotamer candidate. "
                        "Can improve scores when input structure is high quality."
                    ),
                },
                "designable_region": {
                    "type": "string",
                    "enum": ["all", "core", "surface"],
                    "description": (
                        "'all': design every residue (largest search space). "
                        "'core': buried residues only (faster, Dahiyat & Mayo style). "
                        "'surface': exposed residues only."
                    ),
                },
                "rationale": {
                    "type": "string",
                    "description": (
                        "Your explanation for why you chose these parameters "
                        "and what you expect to observe."
                    ),
                },
            },
            "required": ["protein", "ex1", "ex2", "ex1aro", "use_input_sc",
                         "designable_region", "rationale"],
        },
    },
    {
        "name": "get_experiments",
        "description": (
            "Retrieve logged DEE experiments. Returns past runs sorted newest-first. "
            "Use this to review what you've already tried before deciding what to run next."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "protein": {
                    "type": "string",
                    "description": "Filter by PDB ID (optional).",
                },
                "limit": {
                    "type": "integer",
                    "description": "Max number of runs to return (default 20).",
                },
            },
            "required": [],
        },
    },
    {
        "name": "get_summary",
        "description": (
            "Get aggregate statistics across all logged runs: best scores, "
            "fastest runtimes, and parameter breakdowns. "
            "Use this to identify trends and promising regions of the parameter space."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "protein": {
                    "type": "string",
                    "description": "Limit summary to a specific protein (optional).",
                },
            },
            "required": [],
        },
    },
]

# ---------------------------------------------------------------------------
# Tool execution (calls server functions directly)
# ---------------------------------------------------------------------------
def execute_tool(name: str, arguments: dict) -> str:
    if name == "run_dee":
        protein = arguments["protein"]
        ex1 = arguments.get("ex1", False)
        ex2 = arguments.get("ex2", False)
        ex1aro = arguments.get("ex1aro", False)
        use_input_sc = arguments.get("use_input_sc", False)
        designable_region = arguments.get("designable_region", "all")
        rationale = arguments.get("rationale", "")

        print(f"\n>>> Running DEE: {protein} | ex1={ex1} ex2={ex2} ex1aro={ex1aro} "
              f"use_input_sc={use_input_sc} region={designable_region}")
        print(f"    Rationale: {rationale}")

        try:
            metrics = run_dee_experiment(
                protein=protein,
                ex1=ex1, ex2=ex2, ex1aro=ex1aro,
                use_input_sc=use_input_sc,
                designable_region=designable_region,
            )
        except Exception as e:
            return json.dumps({"error": str(e)})

        # Log the run
        record = {
            "id": f"run_{datetime.now(UTC).strftime('%Y%m%d_%H%M%S_%f')}",
            "timestamp": datetime.now(UTC).isoformat(),
            "protein": protein,
            "parameters": {
                "ex1": ex1, "ex2": ex2, "ex1aro": ex1aro,
                "use_input_sc": use_input_sc,
                "designable_region": designable_region,
            },
            "metrics": metrics,
            "rationale": rationale,
            "run_type": "agent",
        }
        _append(record)

        print(f"    Result: final_score={metrics['final_score']:.3f} REU | "
              f"rotamers={metrics['rotamers_pre_dee']} | "
              f"runtime={metrics['runtime_seconds']:.1f}s")

        return json.dumps({
            "run_id": record["id"],
            "metrics": metrics,
            "parameters": record["parameters"],
        }, indent=2)

    elif name == "get_experiments":
        records = _load_all()
        protein = arguments.get("protein")
        if protein:
            records = [r for r in records if r["protein"] == protein]
        records = sorted(records, key=lambda r: r["timestamp"], reverse=True)
        limit = arguments.get("limit", 20)
        return json.dumps(records[:limit], indent=2)

    elif name == "get_summary":
        records = _load_all()
        protein = arguments.get("protein")
        if protein:
            records = [r for r in records if r["protein"] == protein]
        if not records:
            return json.dumps({"status": "no_data", "protein": protein})

        scores = [r["metrics"]["final_score"] for r in records
                  if "final_score" in r.get("metrics", {})]
        runtimes = [r["metrics"]["runtime_seconds"] for r in records
                    if "runtime_seconds" in r.get("metrics", {})]

        best = min(records, key=lambda r: r["metrics"].get("final_score", float("inf")))
        fastest = min(records, key=lambda r: r["metrics"].get("runtime_seconds", float("inf")))

        return json.dumps({
            "total_runs": len(records),
            "scores": {
                "best": min(scores) if scores else None,
                "worst": max(scores) if scores else None,
                "mean": round(sum(scores) / len(scores), 3) if scores else None,
            },
            "runtimes": {
                "fastest_s": min(runtimes) if runtimes else None,
                "slowest_s": max(runtimes) if runtimes else None,
                "mean_s": round(sum(runtimes) / len(runtimes), 3) if runtimes else None,
            },
            "best_run": {
                "id": best["id"],
                "parameters": best["parameters"],
                "final_score": best["metrics"].get("final_score"),
                "rationale": best["rationale"],
            },
            "fastest_run": {
                "id": fastest["id"],
                "parameters": fastest["parameters"],
                "runtime_s": fastest["metrics"].get("runtime_seconds"),
            },
        }, indent=2)

    else:
        return json.dumps({"error": f"Unknown tool: {name}"})


# ---------------------------------------------------------------------------
# Agent loop
# ---------------------------------------------------------------------------
SYSTEM_PROMPT = """You are an AI research agent exploring the parameter space of \
Dead-End Elimination (DEE) for fixed-backbone protein design.

Your goal is to discover parameter configurations that achieve the best \
trade-off between:
  1. Sequence quality (low final energy score in REU — lower is better)
  2. Computational efficiency (low runtime in seconds)
  3. Rotamer pruning (fewer rotamers_pre_dee = more aggressive pruning)

The parameters you can vary are:
  - ex1 / ex2 / ex1aro: rotamer sampling flags (more = finer search, slower)
  - use_input_sc: include input sidechain as rotamer candidate
  - designable_region: 'all', 'core', or 'surface'
    NOTE: 'core' and 'surface' are unreliable for small proteins like 1VII (36 res)
    because the LayerSelector may classify very few residues into those layers,
    resulting in near-trivial design problems. Use 'all' for small proteins.
    'core' and 'surface' are more meaningful for larger proteins like 1PGB (56 res).

Reference point — Dahiyat & Mayo (1997) original paper used:
  ex1=False, ex2=False, ex1aro=False, use_input_sc=False, designable_region='core'

Modern Rosetta default uses:
  ex1=True, ex2=True, ex1aro=False, use_input_sc=True, designable_region='all'

Strategy:
  - Start by reviewing past experiments with get_experiments or get_summary
  - Then run experiments that systematically explore the space
  - Prioritize configurations you haven't tried yet
  - Reason explicitly about what each result tells you before choosing the next run
  - Look for the Pareto frontier: configurations that are fast AND produce good scores
  - Always provide a clear rationale for each run explaining your hypothesis

Be methodical. Each run takes 20-60 seconds of compute, so make each one count."""


def run_agent(protein: str, n_iterations: int, api_key: str) -> None:
    client = anthropic.Anthropic(api_key=api_key)

    print(f"\n{'='*60}")
    print(f"Agentic-DEE | protein={protein} | iterations={n_iterations}")
    print(f"{'='*60}\n")

    messages = [
        {
            "role": "user",
            "content": (
                f"Please explore the DEE parameter space for protein {protein}. "
                f"You have {n_iterations} experiment runs available. "
                f"Start by checking what experiments have already been run, "
                f"then systematically explore the parameter space to find the "
                f"best trade-off between score quality and runtime efficiency. "
                f"Think carefully before each run and explain your reasoning."
            ),
        }
    ]

    iteration = 0
    while iteration < n_iterations:
        response = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=4096,
            system=SYSTEM_PROMPT,
            tools=TOOLS,
            messages=messages,
        )

        # Add assistant response to history
        messages.append({"role": "assistant", "content": response.content})

        # Check if we're done
        if response.stop_reason == "end_turn":
            print("\n--- Agent finished ---")
            # Print final text response
            for block in response.content:
                if hasattr(block, "text"):
                    print(f"\nAgent summary:\n{block.text}")
            break

        # Print agent's reasoning once (before processing tool calls)
        for block in response.content:
            if hasattr(block, "text") and block.text.strip():
                print(f"\nAgent: {block.text.strip()}")
                break

        # Process tool calls
        tool_results = []
        for block in response.content:
            if block.type == "tool_use":
                result = execute_tool(block.name, block.input)

                # Only count run_dee calls as iterations
                if block.name == "run_dee":
                    iteration += 1
                    print(f"  [Iteration {iteration}/{n_iterations}]")

                tool_results.append({
                    "type": "tool_result",
                    "tool_use_id": block.id,
                    "content": result,
                })

        if tool_results:
            messages.append({"role": "user", "content": tool_results})

    print(f"\n{'='*60}")
    print(f"Agent complete. Ran {iteration} experiments.")
    print(f"Results saved to data/logs/experiments.jsonl")
    print(f"{'='*60}\n")


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Agentic-DEE parameter explorer")
    parser.add_argument("--protein", default="1VII",
                        choices=SUPPORTED_PROTEINS,
                        help="Protein to run experiments on")
    parser.add_argument("--iterations", type=int, default=8,
                        help="Number of DEE experiments to run")
    args = parser.parse_args()

    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        print("Error: ANTHROPIC_API_KEY environment variable not set.")
        print("Run: export ANTHROPIC_API_KEY=your_key_here")
        sys.exit(1)

    run_agent(
        protein=args.protein,
        n_iterations=args.iterations,
        api_key=api_key,
    )