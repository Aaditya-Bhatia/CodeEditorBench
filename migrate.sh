#!/usr/bin/env bash
#
# CodeEditorBench repo-level migration script.
# Sets up this project and its conda environment on a fresh server.
# Assumes conda is already installed and available.
#
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

echo "=== CodeEditorBench migration ==="
echo ""

# ── 1. Conda environment ────────────────────────────────────────────────────
if ! command -v conda >/dev/null 2>&1; then
  echo "[FAIL] conda not found in PATH."
  echo "       Install Miniconda first, then re-run this script."
  exit 1
fi

ENV_NAME="codeeditorbench"

if conda env list | grep -q "^${ENV_NAME} "; then
  echo "[1/4] Conda env '${ENV_NAME}' exists — updating..."
else
  echo "[1/4] Creating conda env '${ENV_NAME}'..."
fi
conda env update --file "${SCRIPT_DIR}/coder.yml" --name "${ENV_NAME}" --prune
echo "      Done. Activate with: conda activate ${ENV_NAME}"

# ── 2. Docker judge image ───────────────────────────────────────────────────
if command -v docker >/dev/null 2>&1; then
  if docker image inspect xliudg/code_editor_bench:latest >/dev/null 2>&1; then
    echo "[2/4] Docker judge image already present."
  else
    echo "[2/4] Pulling Docker judge image..."
    docker pull xliudg/code_editor_bench:latest
  fi
else
  echo "[2/4] Docker not found — skipping judge image pull."
  echo "      Install Docker and run: docker pull xliudg/code_editor_bench:latest"
fi

# ── 3. Benchmark data ───────────────────────────────────────────────────────
DATA_DIR="${SCRIPT_DIR}/data"
DATASETS=(
  code_debug_primary.jsonl
  code_translate_primary.jsonl
  code_polishment_primary.jsonl
  code_switch_primary.jsonl
)

MISSING=0
for ds in "${DATASETS[@]}"; do
  if [ ! -f "${DATA_DIR}/${ds}" ]; then
    ((MISSING++))
  fi
done

if [ "${MISSING}" -eq 0 ]; then
  echo "[3/4] All 4 benchmark datasets present."
else
  echo "[3/4] Missing ${MISSING}/4 benchmark datasets in ${DATA_DIR}/"
  echo "      Expected files:"
  for ds in "${DATASETS[@]}"; do
    if [ -f "${DATA_DIR}/${ds}" ]; then
      echo "        [OK]   ${ds}"
    else
      echo "        [MISS] ${ds}"
    fi
  done
  echo "      Copy them from the old server."
fi

# ── 4. Directory structure ──────────────────────────────────────────────────
echo "[4/4] Ensuring output directories..."
mkdir -p "${SCRIPT_DIR}/benchmark_runs"

echo ""
echo "=== Migration complete ==="
echo ""
echo "Quick start:"
echo "  conda activate ${ENV_NAME}"
echo "  python scripts/run_benchmark.py /path/to/vllm_config.yaml"
echo ""
echo "See OPERATIONS.md for full usage."
