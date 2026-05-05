#!/usr/bin/env bash

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
JUDGE_DIR="${1:-${SCRIPT_DIR}/judge}"
CONTAINER_NAME="${CONTAINER_NAME:-codeeditorbench_judge}"
IMAGE_NAME="${IMAGE_NAME:-xliudg/code_editor_bench:latest}"
SHARED_JUDGE_TEMPLATE="${SHARED_JUDGE_TEMPLATE:-}"

docker pull "${IMAGE_NAME}"
if docker container inspect "${CONTAINER_NAME}" >/dev/null 2>&1; then
    echo "Refusing to replace existing container: ${CONTAINER_NAME}" >&2
    exit 1
fi
DOCKER_ARGS=(
    -d
    -v "${JUDGE_DIR}:/home/judge"
    --name "${CONTAINER_NAME}"
)

if [[ -n "${SHARED_JUDGE_TEMPLATE}" ]]; then
    DOCKER_ARGS+=(
        -v "${SHARED_JUDGE_TEMPLATE}/build:/home/judge/build:ro"
        -v "${SHARED_JUDGE_TEMPLATE}/data:/home/judge/data:ro"
        -v "${SHARED_JUDGE_TEMPLATE}/src:/home/judge/src:ro"
        -v "${SHARED_JUDGE_TEMPLATE}/leetcode_template:/home/judge/leetcode_template:ro"
    )
fi

docker run "${DOCKER_ARGS[@]}" "${IMAGE_NAME}"

echo "Judge container started: ${CONTAINER_NAME}"
echo "Enter it with: docker exec -it ${CONTAINER_NAME} /bin/bash"
