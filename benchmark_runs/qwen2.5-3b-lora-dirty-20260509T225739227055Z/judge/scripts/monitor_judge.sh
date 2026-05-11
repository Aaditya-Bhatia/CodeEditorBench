#!/usr/bin/env bash

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/../../.." && pwd)"
CONTAINER_NAME="${CONTAINER_NAME:-codeeditorbench_judge}"
MONITOR_DIR="${REPO_ROOT}/evaluation/judge/monitor"
HISTORY_FILE="${MONITOR_DIR}/history.tsv"
LATEST_FILE="${MONITOR_DIR}/latest_status.txt"
LOCK_DIR="${MONITOR_DIR}/.lock"

mkdir -p "${MONITOR_DIR}"

timestamp_utc() {
    date -u +"%Y-%m-%dT%H:%M:%SZ"
}

log() {
    printf '[%s] %s\n' "$(timestamp_utc)" "$*" >> "${LATEST_FILE}"
}

start_watchdog() {
    docker exec -d "${CONTAINER_NAME}" bash -lc \
        'cd /home/judge/scripts && nohup bash run_judge.sh > /home/judge/scripts/runlog.out 2>&1 < /dev/null &' \
        >/dev/null 2>&1 || true
}

container_running() {
    docker inspect -f '{{.State.Running}}' "${CONTAINER_NAME}" 2>/dev/null
}

mysql_query() {
    local sql="$1"
    docker exec "${CONTAINER_NAME}" bash -lc \
        "mysql -N -B -uroot -proot -e \"use jol; ${sql}\"" 2>/dev/null
}

cleanup_lock() {
    rmdir "${LOCK_DIR}" >/dev/null 2>&1 || true
}

if ! mkdir "${LOCK_DIR}" 2>/dev/null; then
    exit 0
fi
trap cleanup_lock EXIT

: > "${LATEST_FILE}"
log "monitor start"

if [[ "$(container_running || true)" != "true" ]]; then
    log "container ${CONTAINER_NAME} is not running"
    exit 0
fi

if ! docker exec "${CONTAINER_NAME}" bash -lc "ps -eo cmd | grep -q '^bash run_judge.sh$'" >/dev/null 2>&1; then
    log "watchdog missing; restarting run_judge.sh"
    start_watchdog
fi

unresolved="$(mysql_query "select count(*) from solution where model_id>=60 and (result < 4 or result = 14);")"
resolved="$(mysql_query "select count(*) from solution where model_id>=60 and result >= 4 and result != 14;")"
running_clients="$(docker exec "${CONTAINER_NAME}" bash -lc "ps -eo cmd | awk '/judge_client/ { count++ } END { print count + 0 }'" 2>/dev/null | tr -d '[:space:]')"
running_user_code="$(docker exec "${CONTAINER_NAME}" bash -lc "ps -eo cmd | awk '/Main.py/ || /java -Xmx512M -cp .:lib\\/gson-2\\.9\\.1\\.jar Main/ { count++ } END { print count + 0 }'" 2>/dev/null | tr -d '[:space:]')"

now_epoch="$(date -u +%s)"
now_iso="$(timestamp_utc)"

if [[ ! -f "${HISTORY_FILE}" ]]; then
    printf 'timestamp_epoch\ttimestamp_utc\tunresolved\tresolved\trunning_clients\trunning_user_code\n' > "${HISTORY_FILE}"
fi

prev_line="$(tail -n 1 "${HISTORY_FILE}" | awk 'NR==1 && $1 != "timestamp_epoch" {print}')"
eta_text="unknown"
rate_text="unknown"

if [[ -n "${prev_line}" ]]; then
    prev_epoch="$(printf '%s\n' "${prev_line}" | cut -f1)"
    prev_unresolved="$(printf '%s\n' "${prev_line}" | cut -f3)"
    delta_t=$((now_epoch - prev_epoch))
    delta_u=$((prev_unresolved - unresolved))
    if (( delta_t > 0 && delta_u > 0 )); then
        per_hour="$(awk -v du="${delta_u}" -v dt="${delta_t}" 'BEGIN { printf "%.1f", du * 3600 / dt }')"
        eta_hours="$(awk -v rem="${unresolved}" -v du="${delta_u}" -v dt="${delta_t}" 'BEGIN { printf "%.1f", rem / (du * 3600 / dt) }')"
        rate_text="${per_hour} unresolved/hour"
        eta_text="${eta_hours} hours"
    elif (( delta_t > 0 && delta_u == 0 )); then
        rate_text="stalled"
        eta_text="stalled"
    fi
fi

printf '%s\t%s\t%s\t%s\t%s\t%s\n' \
    "${now_epoch}" "${now_iso}" "${unresolved}" "${resolved}" "${running_clients}" "${running_user_code}" \
    >> "${HISTORY_FILE}"

log "queue unresolved=${unresolved} resolved=${resolved}"
log "activity judge_clients=${running_clients} user_code=${running_user_code}"
log "throughput=${rate_text} eta=${eta_text}"
log "per-model queue:"
mysql_query "select concat(model_id, '\t', model_name, '\tqueued=', sum(result=0), '\tjudged=', sum(result>=4 and result!=14)) from solution join models using(model_id) where model_id>=60 group by model_id, model_name order by model_id;" \
    | while IFS= read -r line; do
        log "${line}"
    done

if [[ "${unresolved}" =~ ^[0-9]+$ ]] && (( unresolved > 0 )) && [[ "${running_clients}" =~ ^[0-9]+$ ]] && (( running_clients == 0 )); then
    log "warning: unresolved work exists but no judge_client processes are active"
fi

if [[ "${running_user_code}" =~ ^[0-9]+$ ]] && (( running_user_code > 0 )); then
    log "note: user programs are currently executing inside judge workers"
fi

if [[ "${rate_text}" == "stalled" ]]; then
    log "warning: unresolved queue did not shrink since the last sample"
fi
