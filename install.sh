#!/usr/bin/env bash

set -euo pipefail

ENV_NAME="${1:-codeeditorbench}"

if ! command -v conda >/dev/null 2>&1; then
    echo "conda was not found in PATH"
    exit 1
fi

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

echo "Creating or updating conda env: ${ENV_NAME}"
conda env update --file "${SCRIPT_DIR}/coder.yml" --name "${ENV_NAME}" --prune

echo "Environment ready."
echo "Activate with: conda activate ${ENV_NAME}"
