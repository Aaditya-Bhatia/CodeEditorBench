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
  echo "[3/4] Missing ${MISSING}/4 benchmark datasets — downloading from HuggingFace..."
  mkdir -p "${DATA_DIR}"

  # Use the codeeditorbench env python if available, else system python3
  _dl_python="python3"
  _ceb_prefix="$(conda info --envs 2>/dev/null | grep "^${ENV_NAME} " | awk '{print $NF}' || true)"
  if [[ -n "$_ceb_prefix" && -x "$_ceb_prefix/bin/python" ]]; then
    _dl_python="$_ceb_prefix/bin/python"
  fi
  # Ensure huggingface_hub is available
  "$_dl_python" -c "import huggingface_hub" 2>/dev/null || \
    "$_dl_python" -m pip install --quiet huggingface_hub 2>/dev/null || true

  _downloaded=0
  for ds in "${DATASETS[@]}"; do
    if [ -f "${DATA_DIR}/${ds}" ]; then
      echo "        [OK]   ${ds}"
    else
      echo "        Downloading ${ds}..."
      if "$_dl_python" -c "
from huggingface_hub import hf_hub_download
hf_hub_download('m-a-p/CodeEditorBench', '${ds}', repo_type='dataset', local_dir='${DATA_DIR}')
"; then
        echo "        [OK]   ${ds}"
        ((_downloaded++))
      else
        echo "        [FAIL] ${ds} — install huggingface_hub or copy from old server"
      fi
    fi
  done
  if [ "${_downloaded}" -gt 0 ]; then
    echo "      Downloaded ${_downloaded} dataset(s) from m-a-p/CodeEditorBench"
  fi
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
