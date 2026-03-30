"""
MCP Logging Server for Agentic-DEE experiments.

Provides tools for the agent to:
  - log_experiment : record a completed DEE run with params + metrics
  - get_experiments : retrieve past runs (optionally filtered)
  - get_summary     : get aggregate stats across all runs

Logs are stored as newline-delimited JSON in data/logs/experiments.jsonl
so they're easy to parse, append to, and inspect with standard tools.
"""

import json
import os
from datetime import datetime
from pathlib import Path
from typing import Any

from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import TextContent, Tool

# ---------------------------------------------------------------------------
# Storage
# ---------------------------------------------------------------------------
LOG_DIR = Path("data/logs")
LOG_FILE = LOG_DIR / "experiments.jsonl"
LOG_DIR.mkdir(parents=True, exist_ok=True)


def _load_all() -> list[dict]:
    """Load all experiment records from the log file."""
    if not LOG_FILE.exists():
        return []
    records = []
    with open(LOG_FILE) as f:
        for line in f:
            line = line.strip()
            if line:
                records.append(json.loads(line))
    return records


def _append(record: dict) -> None:
    """Append a single record to the log file."""
    with open(LOG_FILE, "a") as f:
        f.write(json.dumps(record) + "\n")


# ---------------------------------------------------------------------------
# MCP Server
# ---------------------------------------------------------------------------
server = Server("dee-logging")


@server.list_tools()
async def list_tools() -> list[Tool]:
    return [
        Tool(
            name="log_experiment",
            description=(
                "Record a completed DEE run. Stores parameters, metrics, "
                "and agent rationale for later analysis."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "protein": {
                        "type": "string",
                        "description": "PDB ID of the protein (e.g. '1VII')",
                    },
                    "parameters": {
                        "type": "object",
                        "description": (
                            "Parameter configuration used for this run. "
                            "Expected keys: rotamer_sampling (e.g. 'ex1_ex2'), "
                            "designable_region ('all', 'core', 'surface'), "
                            "clash_threshold (float), use_input_sc (bool)"
                        ),
                    },
                    "metrics": {
                        "type": "object",
                        "description": (
                            "Observed metrics from the run. "
                            "Expected keys: initial_score (float), "
                            "final_score (float), score_improvement (float), "
                            "rotamers_pre_dee (int), runtime_seconds (float)"
                        ),
                    },
                    "rationale": {
                        "type": "string",
                        "description": (
                            "Agent's explanation for why this parameter "
                            "configuration was chosen."
                        ),
                    },
                    "run_type": {
                        "type": "string",
                        "enum": ["baseline", "agent", "manual"],
                        "description": "Whether this run was agent-driven or a baseline.",
                    },
                },
                "required": ["protein", "parameters", "metrics", "run_type"],
            },
        ),
        Tool(
            name="get_experiments",
            description=(
                "Retrieve logged experiment runs. Optionally filter by protein "
                "or run_type. Returns runs sorted by timestamp (newest first)."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "protein": {
                        "type": "string",
                        "description": "Filter by protein PDB ID (optional).",
                    },
                    "run_type": {
                        "type": "string",
                        "enum": ["baseline", "agent", "manual"],
                        "description": "Filter by run type (optional).",
                    },
                    "limit": {
                        "type": "integer",
                        "description": "Max number of runs to return (default 20).",
                        "default": 20,
                    },
                },
                "required": [],
            },
        ),
        Tool(
            name="get_summary",
            description=(
                "Get aggregate statistics across all logged runs: best scores, "
                "fastest runtimes, parameter frequency, and score vs runtime "
                "trade-offs. Useful for the agent to identify promising regions "
                "of the parameter space."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "protein": {
                        "type": "string",
                        "description": "Limit summary to a specific protein (optional).",
                    },
                },
                "required": [],
            },
        ),
    ]


@server.call_tool()
async def call_tool(name: str, arguments: dict[str, Any]) -> list[TextContent]:

    # -----------------------------------------------------------------------
    if name == "log_experiment":
        record = {
            "id": f"run_{datetime.utcnow().strftime('%Y%m%d_%H%M%S_%f')}",
            "timestamp": datetime.utcnow().isoformat(),
            "protein": arguments["protein"],
            "parameters": arguments["parameters"],
            "metrics": arguments["metrics"],
            "rationale": arguments.get("rationale", ""),
            "run_type": arguments["run_type"],
        }
        _append(record)
        return [TextContent(
            type="text",
            text=json.dumps({"status": "logged", "run_id": record["id"]}),
        )]

    # -----------------------------------------------------------------------
    elif name == "get_experiments":
        records = _load_all()

        # Apply filters
        if protein := arguments.get("protein"):
            records = [r for r in records if r["protein"] == protein]
        if run_type := arguments.get("run_type"):
            records = [r for r in records if r["run_type"] == run_type]

        # Newest first, apply limit
        records = sorted(records, key=lambda r: r["timestamp"], reverse=True)
        limit = arguments.get("limit", 20)
        records = records[:limit]

        return [TextContent(type="text", text=json.dumps(records, indent=2))]

    # -----------------------------------------------------------------------
    elif name == "get_summary":
        records = _load_all()
        if not records:
            return [TextContent(type="text", text=json.dumps({"status": "no_data"}))]

        if protein := arguments.get("protein"):
            records = [r for r in records if r["protein"] == protein]

        # Aggregate metrics
        scores = [
            r["metrics"]["final_score"]
            for r in records
            if "final_score" in r.get("metrics", {})
        ]
        runtimes = [
            r["metrics"]["runtime_seconds"]
            for r in records
            if "runtime_seconds" in r.get("metrics", {})
        ]
        improvements = [
            r["metrics"]["score_improvement"]
            for r in records
            if "score_improvement" in r.get("metrics", {})
        ]

        # Parameter frequency counts
        param_counts: dict[str, dict] = {}
        for r in records:
            for k, v in r.get("parameters", {}).items():
                param_counts.setdefault(k, {})
                param_counts[k][str(v)] = param_counts[k].get(str(v), 0) + 1

        summary = {
            "total_runs": len(records),
            "proteins": list({r["protein"] for r in records}),
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
            "score_improvements": {
                "best": max(improvements) if improvements else None,
                "mean": round(sum(improvements) / len(improvements), 3) if improvements else None,
            },
            "parameter_frequencies": param_counts,
            "run_types": {
                rt: sum(1 for r in records if r["run_type"] == rt)
                for rt in ["baseline", "agent", "manual"]
            },
        }

        return [TextContent(type="text", text=json.dumps(summary, indent=2))]

    else:
        return [TextContent(type="text", text=json.dumps({"error": f"Unknown tool: {name}"}))]


# ---------------------------------------------------------------------------
# Entrypoint
# ---------------------------------------------------------------------------
async def main():
    async with stdio_server() as (read_stream, write_stream):
        await server.run(read_stream, write_stream, server.create_initialization_options())


if __name__ == "__main__":
    import asyncio
    asyncio.run(main())