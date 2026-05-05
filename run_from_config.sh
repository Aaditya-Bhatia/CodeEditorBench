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

# Activate conda
if ! command -v conda &>/dev/null; then
    for _conda_bin in "${CONDA_EXE}" "$(which conda 2>/dev/null)"; do
        if [[ -n "$_conda_bin" && -x "$_conda_bin" ]]; then
            eval "$("$_conda_bin" shell.bash hook)" && break
        fi
    done
fi
if ! command -v conda &>/dev/null; then
    echo "Error: conda not found in PATH. Install conda or set CONDA_EXE." >&2
    exit 1
fi
if ! conda activate codeeditorbench 2>/dev/null; then
    if ! conda activate coder 2>/dev/null; then
        conda activate SFT_env
    fi
fi

cd "$SCRIPT_DIR"
exec python "$RUNNER" "$@"
