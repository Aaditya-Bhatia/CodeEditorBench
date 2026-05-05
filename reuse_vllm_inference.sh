#!/usr/bin/env bash

set -euo pipefail

API_BASE="${OPENAI_API_BASE:-http://127.0.0.1:9351/v1}"
API_KEY="${OPENAI_API_KEY:-EMPTY}"
API_MODEL="${API_MODEL:-}"
BASE_MODEL="${BASE_MODEL:-deepseek-ai/deepseek-coder-33b-instruct}"
PROMPT_MODEL="${PROMPT_MODEL:-deepseek}"
BATCH_SIZE="${BATCH_SIZE:-64}"
MAX_CONCURRENT="${MAX_CONCURRENT:-64}"
NUM_OF_SEQUENCES="${NUM_OF_SEQUENCES:-1}"
PROMPT_TYPE="${PROMPT_TYPE:-zero}"
START_IDX="${START_IDX:-0}"
END_IDX="${END_IDX:--1}"
INPUT_DATA_DIR="${INPUT_DATA_DIR:-./data/}"
OUTPUT_DATA_DIR="${OUTPUT_DATA_DIR:-./greedy_result/}"

datasets=("debug" "translate" "polishment" "switch")

mkdir -p "${OUTPUT_DATA_DIR}/code_debug" "${OUTPUT_DATA_DIR}/code_translate" "${OUTPUT_DATA_DIR}/code_polishment" "${OUTPUT_DATA_DIR}/code_switch"

for dataset in "${datasets[@]}"; do
    echo "Running ${dataset} against ${API_BASE} with base_model=${BASE_MODEL} api_model=${API_MODEL:-$BASE_MODEL}"
    python openai_compatible_inference.py \
        --base_model "${BASE_MODEL}" \
        --api_model "${API_MODEL:-$BASE_MODEL}" \
        --prompt_model "${PROMPT_MODEL}" \
        --api_base "${API_BASE}" \
        --api_key "${API_KEY}" \
        --dataset "${dataset}" \
        --input_data_dir "${INPUT_DATA_DIR}" \
        --output_data_dir "${OUTPUT_DATA_DIR}" \
        --batch_size "${BATCH_SIZE}" \
        --max_concurrent "${MAX_CONCURRENT}" \
        --num_of_sequences "${NUM_OF_SEQUENCES}" \
        --prompt_type "${PROMPT_TYPE}" \
        --start_idx "${START_IDX}" \
        --end_idx "${END_IDX}"
done
