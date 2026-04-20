#!/bin/bash

PROTEIN=${1:-1VII}
ITERATIONS=${2:-8}

# Derive project root from script location
PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Configurable paths (edit these for your environment)
API_KEY_FILE="${PROJECT_DIR}/claude_api_key.txt"
CONDA_ENV="agenticdee"
LOG_DIR="${PROJECT_DIR}/agent_logs"
TIMESTAMP=$(date +%Y%m%d_%H%M%S)

# Set up environment
export ANTHROPIC_API_KEY=$(cat "${API_KEY_FILE}")
source "$(conda info --base)/etc/profile.d/conda.sh"
conda activate "${CONDA_ENV}"

cd "${PROJECT_DIR}"
mkdir -p "${LOG_DIR}"

python agent/agent.py \
    --protein "${PROTEIN}" \
    --iterations "${ITERATIONS}" \
    2>&1 | tee "${LOG_DIR}/${PROTEIN}_${ITERATIONS}iter_${TIMESTAMP}.log"