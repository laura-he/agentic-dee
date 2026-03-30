# quick test — paste into a python shell from your project root
import json, sys
sys.path.insert(0, "servers")
sys.path.append('/work/sh696/cs590/agentic_dee/agentic-dee')

from servers.logging_server import _append, _load_all
from datetime import datetime

_append({
    "id": "test001",
    "timestamp": datetime.now().isoformat(),
    "protein": "1VII",
    "parameters": {"ex1": True, "ex2": True, "designable_region": "all"},
    "metrics": {"final_score": 38.342, "runtime_seconds": 49.58, "rotamers_before": 14992},
    "rationale": "Baseline run with default parameters.",
    "notes": "",
})

exps = _load_all()
print(json.dumps(exps, indent=2))