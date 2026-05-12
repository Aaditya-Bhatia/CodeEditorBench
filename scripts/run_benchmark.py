#!/usr/bin/env python3
from __future__ import annotations

import argparse
import fcntl
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import yaml

from resume_helpers import (
    missing_positions,
    write_resume_indices_file,
)


DATASETS = ["debug", "translate", "polishment", "switch"]
CODEEDITORBENCH_MAX_TOKENS = 2048
_PROJECTS_ROOT = Path(os.environ.get("PROJECTS_ROOT", str(Path(__file__).resolve().parent.parent.parent)))
DEFAULT_NOTIFY_SCRIPT = str(_PROJECTS_ROOT / "notify_telegram.py")
def _find_master_root() -> Path:
    for name in ("Master_VLLM", "Master-Benchmarking-Orchestrator"):
        candidate = _PROJECTS_ROOT / name
        if candidate.is_dir():
            return candidate
    return _PROJECTS_ROOT / "Master_VLLM"
_MASTER_DIR = _find_master_root()
DEFAULT_MASTER_SYNC_SCRIPT = str(_MASTER_DIR / "master_vllm.py")
DEFAULT_MASTER_MANIFEST = str(_MASTER_DIR / "manifests" / "models_manifest.json")


def parse_args():
    parser = argparse.ArgumentParser(description="Run CodeEditorBench generation from a vLLM YAML config, then launch detached Docker eval.")
    parser.add_argument("config", help="Path to the vLLM YAML config file.")
    parser.add_argument("--prompt-model", default=None, help="Prompt family override for CodeEditorBench.")
    parser.add_argument("--run-name", default=None, help="Explicit benchmark run name. Defaults to <config model_name>-<UTC timestamp>.")
    parser.add_argument("--input-data-dir", default="./data", help="Benchmark dataset directory.")
    parser.add_argument("--output-root", default="./benchmark_runs", help="Directory for benchmark artifacts.")
    parser.add_argument("--judge-template-dir", default="./evaluation/judge", help="Template judge directory used to create an isolated per-run judge workspace.")
    parser.add_argument("--judge-workspace", default=None, help="Optional explicit judge workspace path. Defaults to <run_root>/judge.")
    parser.add_argument("--judge-solution-root", default=None, help="Override the judge staging directory. Defaults to <judge_workspace>/solution_folder.")
    parser.add_argument("--container-name", default=None, help="Optional Docker container name. Defaults to a unique per-run name.")
    parser.add_argument("--notify-script", default=DEFAULT_NOTIFY_SCRIPT, help="Telegram helper script.")
    parser.add_argument("--master-sync-script", default=DEFAULT_MASTER_SYNC_SCRIPT, help="Master_VLLM sync entrypoint for detached CodeEditorBench terminal states.")
    parser.add_argument("--master-manifest", default=DEFAULT_MASTER_MANIFEST, help="Master_VLLM manifest path to refresh from detached CodeEditorBench updates.")
    parser.add_argument("--api-key", default=os.environ.get("OPENAI_API_KEY", "EMPTY"))
    parser.add_argument("--max-concurrent", type=int, default=None, help="Override concurrent request count.")
    parser.add_argument(
        "--dataset-parallelism",
        type=int,
        default=len(DATASETS),
        help="How many benchmark datasets to infer at once during generation. Defaults to all datasets.",
    )
    parser.add_argument("--batch-size", type=int, default=None, help="Override benchmark batch size.")
    parser.add_argument("--start-idx", type=int, default=0)
    parser.add_argument("--end-idx", type=int, default=-1)
    parser.add_argument("--eval-max-wait-seconds", type=int, default=4 * 60 * 60, help="Maximum wall-clock time to wait for detached evaluation to finish.")
    parser.add_argument("--eval-stall-timeout-seconds", type=int, default=30 * 60, help="Fail detached evaluation if queue status stops making progress for this long.")
    parser.add_argument("--generation-only", action="store_true", help="Run generation and postprocessing only, skip Docker evaluation.")
    return parser.parse_args()


def sanitize_model_name(value: str) -> str:
    return value.split("/")[-1].replace("-", "_").replace(".", "_")


def default_container_name(run_name: str) -> str:
    safe = re.sub(r"[^a-zA-Z0-9_.-]+", "-", run_name).strip("-_.").lower() or "run"
    digest = hashlib.sha1(run_name.encode("utf-8")).hexdigest()[:10]
    return f"codeeditorbench_judge_{safe[:40]}_{digest}"


def run_command(cmd, cwd, env=None):
    print("$", " ".join(cmd))
    subprocess.run(cmd, cwd=cwd, env=env, check=True)


def start_command(cmd, cwd, log_path: Path, env=None):
    print("$", " ".join(cmd))
    log_handle = log_path.open("w")
    process = subprocess.Popen(
        cmd,
        cwd=cwd,
        env=env,
        stdout=log_handle,
        stderr=subprocess.STDOUT,
    )
    return process, log_handle


def send_telegram(notify_script: str, message: str):
    if not notify_script or not os.path.exists(notify_script):
        print(f"Telegram notify script not found, skipping: {notify_script}")
        return
    subprocess.run([sys.executable, notify_script, message], check=False)


def benchmark_message(model_name: str, state: str) -> str:
    return f"CodeEditorBench | {model_name} | {state}"


def load_config(path: Path):
    with path.open() as f:
        return yaml.safe_load(f)


def update_summary(path: Path, **updates):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a+", encoding="utf-8") as handle:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        handle.seek(0)
        raw = handle.read().strip()
        data = json.loads(raw) if raw else {}
        data.update(updates)
        tmp_path = path.with_name(f".{path.name}.{os.getpid()}.{time.time_ns()}.tmp")
        with tmp_path.open("w", encoding="utf-8") as tmp_handle:
            json.dump(data, tmp_handle, indent=2)
            tmp_handle.write("\n")
            tmp_handle.flush()
            os.fsync(tmp_handle.fileno())
        os.replace(tmp_path, path)
        dir_fd = os.open(str(path.parent), os.O_DIRECTORY)
        try:
            os.fsync(dir_fd)
        finally:
            os.close(dir_fd)
        fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def resolve_prompt_model(config, explicit_prompt_model):
    if explicit_prompt_model:
        return explicit_prompt_model
    if config.get("prompt_model"):
        return config["prompt_model"]

    source = " ".join(
        str(config.get(key, "")) for key in ("model_name", "model_path", "served_model_name")
    ).lower()
    if "codellama" in source and "instruct" in source:
        return "codellama-inst"
    if "codellama" in source:
        return "codellama"
    if "wizard" in source:
        return "wizardcoder"
    if "magic" in source:
        return "magicoder"
    if "octo" in source:
        return "octocoder"
    if "codefuse" in source:
        return "codefuse"
    if "phind" in source:
        return "phind"
    return "deepseek"


def build_run_name(config, explicit_run_name):
    if explicit_run_name:
        return explicit_run_name
    base_name = config.get("model_name") or Path(config["model_path"]).name
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    return f"{base_name}-{timestamp}"


def prepare_judge_workspace(template_dir: Path, workspace_dir: Path):
    if workspace_dir.exists():
        shutil.rmtree(workspace_dir)
    workspace_dir.mkdir(parents=True, exist_ok=True)
    for name in ["build", "data", "src", "leetcode_template"]:
        (workspace_dir / name).mkdir(parents=True, exist_ok=True)

    for name in ["etc", "scripts"]:
        src = template_dir / name
        dst = workspace_dir / name
        try:
            subprocess.run(["cp", "-al", str(src), str(dst)], check=True)
        except subprocess.CalledProcessError:
            if dst.exists():
                shutil.rmtree(dst)
            if src.is_dir():
                shutil.copytree(src, dst)
            else:
                shutil.copy2(src, dst)

    stale_files = [
        workspace_dir / "etc" / "judge.pid",
        workspace_dir / "scripts" / "runlog.out",
    ]
    for stale_file in stale_files:
        if stale_file.exists():
            stale_file.unlink()

    pycache_dir = workspace_dir / "scripts" / "__pycache__"
    if pycache_dir.exists():
        shutil.rmtree(pycache_dir)

    for subdir in ["code_debug", "code_translate", "code_polishment", "code_switch", "processed_solution"]:
        (workspace_dir / "solution_folder" / subdir).mkdir(parents=True, exist_ok=True)
    for subdir in ["log", "monitor", "metrics"]:
        (workspace_dir / subdir).mkdir(parents=True, exist_ok=True)
    for idx in range(50):
        (workspace_dir / f"run{idx}" / "log").mkdir(parents=True, exist_ok=True)


def terminate_process(process: subprocess.Popen, dataset: str, timeout_seconds: int = 10):
    if process.poll() is not None:
        return
    print(f"Stopping generation worker for dataset={dataset} pid={process.pid}")
    process.terminate()
    try:
        process.wait(timeout=timeout_seconds)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait()


def wait_for_generation_jobs(jobs):
    pending = dict(jobs)
    while pending:
        for dataset, job in list(pending.items()):
            return_code = job["process"].poll()
            if return_code is None:
                continue
            job["return_code"] = return_code
            del pending[dataset]
            if return_code != 0:
                for other_dataset, other_job in pending.items():
                    terminate_process(other_job["process"], other_dataset)
                raise RuntimeError(
                    f"Generation failed for dataset={dataset} return_code={return_code} log={job['log_path']}"
                )
        if pending:
            time.sleep(1)


def run_generation_jobs(repo_root: Path, logs_root: Path, commands_by_dataset):
    jobs = {}
    try:
        for dataset, cmd in commands_by_dataset.items():
            log_path = logs_root / f"generation_{dataset}.log"
            process, log_handle = start_command(cmd, cwd=str(repo_root), log_path=log_path)
            jobs[dataset] = {
                "cmd": cmd,
                "process": process,
                "log_handle": log_handle,
                "log_path": str(log_path),
            }
        wait_for_generation_jobs(jobs)
    finally:
        for dataset, job in jobs.items():
            if job["process"].poll() is None:
                terminate_process(job["process"], dataset)
            job["log_handle"].close()
    return {
        dataset: {
            "pid": job["process"].pid,
            "log_path": job["log_path"],
            "return_code": job.get("return_code", job["process"].returncode),
        }
        for dataset, job in jobs.items()
    }


def _build_inference_cmd(
    *,
    run_name: str,
    api_model: str,
    prompt_model: str,
    api_base: str,
    api_key: str,
    dataset: str,
    input_data_dir: str,
    raw_root: Path,
    batch_size: int,
    max_concurrent: int,
    temperature: float,
    top_p: float,
    top_k,
    start_idx: int,
    end_idx: int,
    resume_indices_file: Path | None,
) -> list[str]:
    """Compose the openai_compatible_inference.py argv. In fresh mode we pass
    --start_idx/--end_idx as before. In resume mode we pass
    --resume-indices-file instead; the inference script then ignores
    start/end and processes exactly the listed positions."""
    cmd = [
        sys.executable,
        "openai_compatible_inference.py",
        "--base_model",
        run_name,
        "--api_model",
        api_model,
        "--prompt_model",
        prompt_model,
        "--api_base",
        api_base,
        "--api_key",
        api_key,
        "--dataset",
        dataset,
        "--input_data_dir",
        input_data_dir,
        "--output_data_dir",
        str(raw_root),
        "--batch_size",
        str(batch_size),
        "--max_concurrent",
        str(max_concurrent),
        "--num_of_sequences",
        "1",
        "--temperature",
        str(temperature),
        "--top_p",
        str(top_p),
        "--max_tokens",
        str(CODEEDITORBENCH_MAX_TOKENS),
        "--prompt_type",
        "zero",
        "--start_idx",
        str(start_idx),
        "--end_idx",
        str(end_idx),
    ]
    if top_k is not None:
        cmd.extend(["--top_k", str(top_k)])
    if resume_indices_file is not None:
        cmd.extend(["--resume-indices-file", str(resume_indices_file)])
    return cmd


def _load_resume_plan(config: dict) -> dict | None:
    """If the YAML embeds codeeditorbench.resume_from_run_name, return a small
    dict the main flow can branch on. Otherwise None.

    The orchestrator (master_vllm_utils.build_runtime_config) is the only
    producer of this block; see _codeeditorbench_resume_target there.
    """
    block = config.get("codeeditorbench")
    if not isinstance(block, dict):
        return None
    run_name = block.get("resume_from_run_name")
    datasets = block.get("resume_datasets") or []
    if not run_name or not datasets:
        return None
    return {
        "run_name": str(run_name),
        "datasets": [str(d) for d in datasets],
        "previous_attempts": int(block.get("previous_attempts") or 0),
    }


def _rotate_dataset_log(logs_root: Path, dataset: str, previous_attempts: int) -> None:
    """Move generation_<dataset>.log → generation_<dataset>.log.attempt<n> so
    the next inference run writes a fresh log. Critical because the orchestrator
    counts ``[WARN] Skipping prompt`` text occurrences to classify run health —
    without rotation, the old skips would falsely flag the resumed run.
    """
    log_path = logs_root / f"generation_{dataset}.log"
    if not log_path.exists():
        return
    archived = logs_root / f"generation_{dataset}.log.attempt{previous_attempts}"
    if archived.exists():
        archived.unlink()
    log_path.rename(archived)


def _remove_judge_container(container_name: str) -> None:
    """Best-effort tear-down of a per-run judge container before its bind-
    mounted judge_dir is wiped on resume. Safe to call if no such container
    exists — docker rm -f is a no-op then. Also a no-op when docker isn't
    installed on the host (e.g. boxes where judge eval runs elsewhere); the
    judge_dir rmtree below still succeeds without container teardown."""
    try:
        subprocess.run(
            ["docker", "rm", "-f", container_name],
            check=False,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    except FileNotFoundError:
        # docker binary not on PATH — nothing to tear down.
        pass


def main():
    args = parse_args()
    repo_root = Path(__file__).resolve().parents[1]
    config_path = Path(args.config).resolve()
    config = load_config(config_path)
    resume_plan = _load_resume_plan(config)
    run_name = (resume_plan["run_name"] if resume_plan else build_run_name(config, args.run_name))
    prompt_model = resolve_prompt_model(config, args.prompt_model)
    api_base = config.get("api_base") or f"http://127.0.0.1:{config['port']}/v1"
    api_model = config.get("served_model_name") or config.get("model_name")
    display_model_name = config.get("model_name") or api_model
    batch_size = args.batch_size or config.get("batch_size", 32)
    max_concurrent = args.max_concurrent or config.get("max_workers", batch_size)
    dataset_parallelism = max(1, min(args.dataset_parallelism, len(DATASETS)))
    output_root = (repo_root / args.output_root).resolve()
    run_root = output_root / run_name
    if resume_plan is None:
        if run_root.exists():
            raise FileExistsError(f"Refusing to reuse existing run directory: {run_root}")
    else:
        if not run_root.is_dir():
            raise FileNotFoundError(
                f"Resume requested for run_name={run_name} but run directory does not exist: {run_root}"
            )
    raw_root = run_root / "raw"
    clean_root = run_root / "clean"
    logs_root = run_root / "logs"
    judge_template_dir = (repo_root / args.judge_template_dir).resolve()
    judge_dir = Path(args.judge_workspace).resolve() if args.judge_workspace else (run_root / "judge").resolve()
    judge_solution_root = Path(args.judge_solution_root).resolve() if args.judge_solution_root else (judge_dir / "solution_folder").resolve()
    container_name = args.container_name or default_container_name(run_name)
    logs_root.mkdir(parents=True, exist_ok=True)
    summary_path = run_root / "summary.json"
    staged_name = f"{run_name}.jsonl"
    raw_output_basename = f"{sanitize_model_name(run_name)}_{args.start_idx}_{args.end_idx if args.end_idx != -1 else 'end'}.jsonl"

    if resume_plan is None:
        summary = {
            "run_name": run_name,
            "config_path": str(config_path),
            "api_base": api_base,
            "api_model": api_model,
            "model_name": display_model_name,
            "prompt_model": prompt_model,
            "batch_size": batch_size,
            "max_concurrent": max_concurrent,
            "dataset_parallelism": dataset_parallelism,
            "datasets": DATASETS,
            "raw_root": str(raw_root),
            "clean_root": str(clean_root),
            "judge_template_dir": str(judge_template_dir),
            "judge_dir": str(judge_dir),
            "judge_solution_root": str(judge_solution_root),
            "container_name": container_name,
            "status": "running_generation",
            "generation_started_at_utc": datetime.now(timezone.utc).isoformat(),
            "attempts": 0,
        }
        run_root.mkdir(parents=True, exist_ok=True)
        prepare_judge_workspace(judge_template_dir, judge_dir)
        update_summary(summary_path, **summary)
        active_datasets = list(DATASETS)
        resume_indices_files: dict[str, Path] = {}
    else:
        # Resume mode: same run_root, flip status back to running_generation,
        # bump attempts, clear stale failure fields. Compute the missing
        # positions for each recoverable dataset, rotate its prior log, and
        # remember the indices file so we pass --resume-indices-file below.
        previous_attempts = resume_plan["previous_attempts"]
        active_datasets = [d for d in resume_plan["datasets"] if d in DATASETS]
        if not active_datasets:
            raise ValueError(
                f"Resume plan provided no recoverable datasets matching {DATASETS}: {resume_plan['datasets']}"
            )
        resume_indices_files = {}
        empty_datasets: list[str] = []
        for dataset in active_datasets:
            raw_jsonl = raw_root / f"code_{dataset}" / raw_output_basename
            input_data_path = (repo_root / args.input_data_dir / f"code_{dataset}_primary.jsonl").resolve()
            positions = missing_positions(input_data_path, raw_jsonl)
            if not positions:
                # The classifier said there were skips but no gaps remain in
                # the raw output — this means previous skips happened on rows
                # that were later filled (unlikely but possible). Nothing to
                # do for this dataset.
                empty_datasets.append(dataset)
                continue
            indices_file = logs_root / f"resume_{dataset}_attempt{previous_attempts + 1}.indices"
            write_resume_indices_file(positions, indices_file)
            resume_indices_files[dataset] = indices_file
            _rotate_dataset_log(logs_root, dataset, previous_attempts)
        for d in empty_datasets:
            active_datasets.remove(d)
        # Stop+remove any prior judge container so its bind-mount on judge_dir
        # is released before we rmtree it. The previous detached worker
        # should already have exited (resume only fires after generation_failed),
        # but the container can outlive the worker.
        _remove_judge_container(container_name)
        # Prepare a fresh judge workspace — prepare_judge_workspace rmtree's
        # the dir, so this is safe to call again in resume mode and ensures
        # the judge sees clean state.
        prepare_judge_workspace(judge_template_dir, judge_dir)
        update_summary(
            summary_path,
            status="running_generation",
            attempts=previous_attempts + 1,
            last_resume_started_at_utc=datetime.now(timezone.utc).isoformat(),
            last_resume_datasets=list(active_datasets),
            error=None,
            generation_failed_at_utc=None,
            eval_failed_at_utc=None,
            eval_completed_at_utc=None,
            metrics_path=None,
        )

    commands_by_dataset: dict[str, list[str]] = {}
    generation_logs: dict[str, str] = {}
    for dataset in active_datasets:
        commands_by_dataset[dataset] = _build_inference_cmd(
            run_name=run_name,
            api_model=api_model,
            prompt_model=prompt_model,
            api_base=api_base,
            api_key=args.api_key,
            dataset=dataset,
            input_data_dir=args.input_data_dir,
            raw_root=raw_root,
            batch_size=batch_size,
            max_concurrent=max_concurrent,
            temperature=config.get("temperature", 0.0),
            top_p=config.get("top_p", 1.0),
            top_k=config.get("top_k"),
            start_idx=args.start_idx,
            end_idx=args.end_idx,
            resume_indices_file=resume_indices_files.get(dataset) if resume_plan else None,
        )
        generation_logs[dataset] = str(logs_root / f"generation_{dataset}.log")

    # In resume mode we merge the new per-dataset log paths into the existing
    # generation_logs map rather than overwriting it, so the classifier still
    # sees the (rotated) untouched datasets' log paths if they're referenced.
    if resume_plan:
        existing_logs = {}
        try:
            existing = json.loads(summary_path.read_text(encoding="utf-8"))
            existing_logs = existing.get("generation_logs") or {}
        except (OSError, json.JSONDecodeError):
            existing_logs = {}
        merged_logs = {**existing_logs, **generation_logs}
        update_summary(summary_path, generation_logs=merged_logs)
    else:
        update_summary(summary_path, generation_logs=generation_logs)

    try:
        generation_job_info = {}
        if commands_by_dataset:
            if dataset_parallelism >= len(active_datasets):
                generation_job_info = run_generation_jobs(repo_root, logs_root, commands_by_dataset)
            else:
                dataset_queue = list(active_datasets)
                while dataset_queue:
                    chunk = dataset_queue[:dataset_parallelism]
                    dataset_queue = dataset_queue[dataset_parallelism:]
                    chunk_commands = {dataset: commands_by_dataset[dataset] for dataset in chunk}
                    generation_job_info.update(run_generation_jobs(repo_root, logs_root, chunk_commands))
        else:
            # Resume mode with no actual gaps to fill — proceed straight to
            # postprocess + judge.
            generation_job_info = {}
    except Exception as exc:
        update_summary(
            summary_path,
            status="generation_failed",
            generation_failed_at_utc=datetime.now(timezone.utc).isoformat(),
            generation_error=str(exc),
        )
        raise

    update_summary(summary_path, generation_jobs=generation_job_info)

    try:
        run_command(
            [
                sys.executable,
                "result_postprocess.py",
                "--input-root",
                str(raw_root),
                "--output-root",
                str(clean_root),
                "--files",
                raw_output_basename,
            ],
            cwd=str(repo_root),
        )

        for dataset in DATASETS:
            source_path = clean_root / f"code_{dataset}" / raw_output_basename
            target_dir = judge_solution_root / f"code_{dataset}"
            target_dir.mkdir(parents=True, exist_ok=True)
            target_path = target_dir / staged_name
            if not source_path.exists():
                raise FileNotFoundError(f"Expected processed output missing: {source_path}")
            shutil.copyfile(source_path, target_path)

        worker = None
        eval_log_path = None
        if args.generation_only:
            print(f"=== Generation complete (--generation-only). Outputs in: {clean_root} ===")
        else:
            eval_log_path = logs_root / "detached_eval.log"
            worker_cmd = [
                sys.executable,
                str(repo_root / "scripts" / "detached_eval_worker.py"),
                "--run-name",
                run_name,
                "--model-name",
                display_model_name,
                "--config-path",
                str(config_path),
                "--container-name",
                container_name,
                "--judge-dir",
                str(judge_dir),
                "--judge-template-dir",
                str(judge_template_dir),
                "--notify-script",
                args.notify_script,
                "--master-sync-script",
                args.master_sync_script,
                "--master-manifest",
                args.master_manifest,
                "--summary-path",
                str(summary_path),
                "--max-wait-seconds",
                str(args.eval_max_wait_seconds),
                "--stall-timeout-seconds",
                str(args.eval_stall_timeout_seconds),
            ]
            with eval_log_path.open("w") as log_file:
                worker = subprocess.Popen(
                    worker_cmd,
                    cwd=str(repo_root),
                    stdout=log_file,
                    stderr=subprocess.STDOUT,
                    start_new_session=True,
                )
    except Exception as exc:
        update_summary(
            summary_path,
            status="generation_failed",
            generation_failed_at_utc=datetime.now(timezone.utc).isoformat(),
            error=str(exc),
        )
        raise

    update_summary(
        summary_path,
        status="generation_complete",
        staged_name=staged_name,
        eval_worker_pid=worker.pid if worker else None,
        eval_log_path=str(eval_log_path) if eval_log_path else None,
        generation_completed_at_utc=datetime.now(timezone.utc).isoformat(),
        error=None,
        generation_failed_at_utc=None,
        eval_failed_at_utc=None,
        eval_completed_at_utc=None,
        metrics_path=None,
    )

    if args.generation_only:
        send_telegram(
            args.notify_script,
            benchmark_message(display_model_name, "generation_complete (gen-only)"),
        )
    else:
        send_telegram(
            args.notify_script,
            benchmark_message(display_model_name, "eval_pending"),
        )
    summary = json.loads(summary_path.read_text())
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
