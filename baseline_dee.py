"""
Baseline Dead-End Elimination (DEE) run on 1VII (villin headpiece).
Uses PyRosetta with default parameters — this is the comparison target
for the agentic optimization experiments.
"""

import time
import pyrosetta
from pyrosetta import pose_from_pdb
from pyrosetta.rosetta.core.pack.task import TaskFactory
from pyrosetta.rosetta.core.pack.task.operation import (
    InitializeFromCommandline,
    RestrictToRepacking,
)
from pyrosetta.rosetta.protocols.minimization_packing import PackRotamersMover

# ---------------------------------------------------------------------------
# 1. Initialize PyRosetta
# ---------------------------------------------------------------------------
pyrosetta.init(
    options="-ex1 -ex2 -use_input_sc",
    extra_options="-constant_seed",  # fixes RNG seed for reproducibility
    silent=True,
)

# ---------------------------------------------------------------------------
# 2. Load structure
# ---------------------------------------------------------------------------
PDB_PATH = "data/pdbs/1VII.pdb"  # adjust path if needed
pose = pose_from_pdb(PDB_PATH)

print(f"Loaded: {PDB_PATH}")
print(f"  Residues : {pose.total_residue()}")
print(f"  Sequence : {pose.sequence()}")

# ---------------------------------------------------------------------------
# 3. Score function — ref2015 is the modern Rosetta standard
# ---------------------------------------------------------------------------
scorefxn = pyrosetta.create_score_function("ref2015")
initial_score = scorefxn(pose)
print(f"\nInitial score (REU): {initial_score:.3f}")

# ---------------------------------------------------------------------------
# 4. Packer task — design all residues (no restrictions)
# ---------------------------------------------------------------------------
task_factory = TaskFactory()
task_factory.push_back(InitializeFromCommandline())
# To restrict to repack-only (no sequence design), uncomment the next line:
# task_factory.push_back(RestrictToRepacking())

packer_task = task_factory.create_task_and_apply_taskoperations(pose)

# Count total rotamers before DEE pruning
rotamer_sets = pyrosetta.rosetta.core.pack.rotamer_set.RotamerSets()
packer_graph = pyrosetta.rosetta.core.pack.create_packer_graph(
    pose, scorefxn, packer_task
)
rotamer_sets.set_task(packer_task)
rotamer_sets.initialize_pose_for_rotsets_creation(pose)
rotamer_sets.build_rotamers(pose, scorefxn, packer_graph)

total_rotamers_before = sum(
    rotamer_sets.rotamer_set_for_residue(i).num_rotamers()
    for i in range(1, pose.total_residue() + 1)
    if packer_task.being_packed(i)
)
print(f"\nRotamers before DEE: {total_rotamers_before}")

# ---------------------------------------------------------------------------
# 5. Run DEE via PackRotamersMover (DEE is run internally before packing)
# ---------------------------------------------------------------------------
pack_mover = PackRotamersMover(scorefxn, packer_task)

start_time = time.time()
pack_mover.apply(pose)
elapsed = time.time() - start_time

final_score = scorefxn(pose)

# ---------------------------------------------------------------------------
# 6. Report results
# ---------------------------------------------------------------------------
print(f"\n{'='*50}")
print("BASELINE DEE RESULTS")
print(f"{'='*50}")
print(f"  Protein          : 1VII (villin headpiece, {pose.total_residue()} res)")
print(f"  Score function   : ref2015")
print(f"  Rotamer sampling : -ex1 -ex2 (default)")
print(f"  Designable res   : all {pose.total_residue()}")
print(f"  Rotamers (pre-DEE): {total_rotamers_before}")
print(f"  Initial score    : {initial_score:.3f} REU")
print(f"  Final score      : {final_score:.3f} REU")
print(f"  Score improvement: {initial_score - final_score:.3f} REU")
print(f"  Runtime          : {elapsed:.2f}s")
print(f"{'='*50}")