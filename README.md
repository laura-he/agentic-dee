# Agentic-DEE: An Agentic-AI Approach to Parameter Optimization for Dead-End Elimination in Fixed-Backbone Protein Design

Agentic-DEE uses a Claude Haiku agent to autonomously explore parameter configurations for Dead-End Elimination (DEE) in fixed-backbone protein design via PyRosetta. Rather than relying on manual tuning or grid search, the agent iteratively proposes, executes, and interprets DEE runs, using experiment history to inform each decision. Tested across three benchmark proteins, the agent demonstrated adaptive, hypothesis-driven exploration. It finds a configuration on 1PGB that outperforms the modern Rosetta default by 6.4 REU at 47% lower runtime.

# Creating the Environment
1. Create a virtual environment to keep things neat. I recommend Miniconda, which you can install from here: https://www.anaconda.com/docs/getting-started/miniconda/install/overview
2. Clone the GitHub repository:
```bash
git clone git@github.com:laura-he/agentic-dee.git
cd agentic-dee
```

3. Create and activate the Agentic-DEE environment:
```bash
conda create -n agentic_dee -c conda-forge python=3.12 pip
conda activate agentic_dee
```

4. Install the core package and dependencies:
```bash
pip install -r requirements_minimal.txt
```

5. To install PyRosetta, follow the instructions here: https://www.pyrosetta.org/downloads

In brief:
```bash
pip install pyrosetta --find-links https://west.rosettacommons.org/pyrosetta/quarterly/release
```
**Note: This is for academic use only. See https://www.pyrosetta.org for license details.**

6. To run the agent:
```bash
export ANTHROPIC_API_KEY=$(cat ${path_to_api_key})
python agent/agent.py --protein 1L2Y --iterations 8 2>&1 | tee ${log_path}/${timestamp}.log
```
This command sets the environment variable ```ANTHROPIC_API_KEY``` to the path to your API key (```path_to_api_key```) and runs 8 iterations of DEE on the protein ```1L2Y```.

# Downloading PDB Files
You can directly download the PDB files for the 3 proteins used in this project (```1PGB```, ```1VII```, ```1L2Y```) from the RCSB PDB.

## Via the Browser
Go to https://www.rcsb.org/structure/1PGB (swap in the other IDs) and click "Download Files" → "PDB Format."

## Via ```curl```
```bash
for pdb in 1PGB 1VII 1L2Y; do
  curl -O https://files.rcsb.org/download/${pdb}.pdb
done
```

For storage purposes, the PDB structures are *not* provided in this GitHub repository.

# API Key Setup
To obtain an Anthropic API key:
1. Create or sign in to an Anthropic account: https://platform.claude.com/login?returnTo=%2F%3F
2. On the home page, click on the button `Get API Key`
3. Click on the button `+ Create key`
4. Give your key a name and select `Add`
5. The API key will be displayed as a long string. Copy this key and store it in a safe location. For instance, you could create a file called `claude_api_key.txt` in the project root containing your Anthropic API key. This file is gitignored and should never be committed.
   