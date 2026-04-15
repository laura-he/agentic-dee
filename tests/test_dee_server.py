import sys
sys.path.insert(0, "servers")
sys.path.append('/work/sh696/cs590/agentic_dee/agentic-dee')
from servers.dee_server import run_dee_experiment

# Paper-faithful config — no extra sampling
result = run_dee_experiment(
    protein="1VII",
    ex1=False, ex2=False, ex1aro=False,
    use_input_sc=False,
    designable_region="all",
)
print(result)