#!/usr/bin/env bash
# Reads a Master_VLLM runtime YAML and runs CodeEditorBench generation +
# detached Docker evaluation. Mirrors CanItEdit / HumanEvalFix's run_from_config.sh
# so Master_VLLM can schedule this benchmark with its standard `[runner, config]`
# calling convention.
#
# Usage: ./run_from_config.sh <config.yaml> [extra args forwarded to scripts/run_benchmark.py]
#
# Behavior:
#   1. Activates the `codeeditorbench` conda env (falls back to `coder`, then SFT_env).
#   2. Calls scripts/run_benchmark.py which:
#        - reads port / model_name / served_model_name / temperature / top_p /
#          max_tokens / max_workers / batch_size from the YAML
#        - runs all four datasets (debug, translate, polishment, switch) in parallel
#          against the already-running vLLM server
#        - postprocesses outputs, stages them into the judge, launches a
#          detached Docker eval worker, and sends Telegram notifications
#   3. Returns as soon as generation + eval-launch succeed. The Docker judge
#      keeps running in the background and updates benchmark_runs/<run>/summary.json.
set -eo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
RUNNER="$SCRIPT_DIR/scripts/run_benchmark.py"

if [[ $# -lt 1 ]]; then
    echo "Usage: $(basename "$0") <config.yaml> [extra args forwarded to scripts/run_benchmark.py]"
    exit 1
fi

CONFIG_FILE="$1"
if [[ ! -f "$CONFIG_FILE" ]]; then
    echo "Error: Config file not found: $CONFIG_FILE"
    exit 1
fi

if [[ ! -f "$RUNNER" ]]; then
    echo "Error: runner not found at $RUNNER"
    exit 1
fi

# Activate conda — always run the shell hook so `conda activate` works
_conda_bin="${CONDA_EXE:-$(command -v conda 2>/dev/null || echo "$HOME/miniconda3/bin/conda")}"
if [[ -x "$_conda_bin" ]]; then
    eval "$("$_conda_bin" shell.bash hook)"
else
    echo "Error: conda not found. Set CONDA_EXE or add conda to PATH." >&2
    exit 1
fi
if ! conda activate codeeditorbench 2>/dev/null; then
    if ! conda activate coder 2>/dev/null; then
        conda activate SFT_env
    fi
fi

cd "$SCRIPT_DIR"

# Check if the YAML config requests generation-only mode
_gen_only=""
if [[ -f "$1" ]]; then
    _gen_only="$(python -c "
import yaml, sys
with open(sys.argv[1]) as f:
    c = yaml.safe_load(f)
print('yes' if c.get('generation_only', False) else 'no')
" "$1" 2>/dev/null || echo "no")"
fi

if [[ "$_gen_only" == "yes" ]]; then
    exec python "$RUNNER" "$@" --generation-only
else
    exec python "$RUNNER" "$@"
fi
