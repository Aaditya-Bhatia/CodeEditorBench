"""Helpers for resuming a partial CodeEditorBench generation run.

The orchestrator detects partial runs via
``benchmark_results.codeeditorbench_resumable_datasets`` and threads a list of
recoverable datasets into the runner. For each, we need to figure out which
specific samples are missing from the raw JSONL and re-run only those — the
auto-resume logic in ``openai_compatible_inference.py`` keys off line counts
and so silently drops skipped prompts, which is the exact failure mode we are
trying to fix.

Each function here is small and independently testable; ``run_benchmark.py``
glues them together.
"""

from __future__ import annotations

import json
from pathlib import Path


def input_dataset_problem_ids(input_data_path: Path) -> list[int]:
    """Return the dataset's ``idx`` values in input-file order.

    ``openai_compatible_inference.py`` writes each output row with
    ``"problem_id": batch["idx"][..]``, where ``idx`` comes from
    ``dataset.JsonlDataset``. The returned list's index is the 0-based list
    position used for slicing; the value is the ``idx`` field as stored in
    the raw output as ``problem_id``.
    """
    problem_ids: list[int] = []
    with input_data_path.open("r", encoding="utf-8") as fh:
        for position, line in enumerate(fh):
            line = line.strip()
            if not line:
                continue
            row = json.loads(line)
            problem_ids.append(int(row.get("idx", position)))
    return problem_ids


def written_problem_ids(raw_jsonl_path: Path) -> set[int]:
    """Return the set of ``problem_id`` values present in an existing raw
    output JSONL. The first line is a metadata header (no ``problem_id``);
    it is silently skipped. Malformed rows are ignored — we'd rather under-
    count and rerun a row than treat a corrupt write as successful.
    """
    found: set[int] = set()
    if not raw_jsonl_path.is_file():
        return found
    with raw_jsonl_path.open("r", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue
            pid = row.get("problem_id")
            if isinstance(pid, int):
                found.add(pid)
    return found


def missing_positions(input_data_path: Path, raw_jsonl_path: Path) -> list[int]:
    """Return the 0-based list positions in the input dataset whose rows are
    not yet present in the raw output JSONL.

    Positions (not ``problem_id``s) are returned because
    ``openai_compatible_inference.py`` consumes the dataset by list position
    via ``torch.utils.data.Subset``. The orchestrator caller treats this list
    as opaque.
    """
    problem_ids = input_dataset_problem_ids(input_data_path)
    written = written_problem_ids(raw_jsonl_path)
    return [pos for pos, pid in enumerate(problem_ids) if pid not in written]


def write_resume_indices_file(positions: list[int], target: Path) -> Path:
    """Persist the position list to a newline-delimited file consumable by
    ``openai_compatible_inference.py --resume-indices-file``. Returns the
    target path."""
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        "\n".join(str(p) for p in positions) + ("\n" if positions else ""),
        encoding="utf-8",
    )
    return target


def read_resume_indices_file(source: Path) -> list[int]:
    """Inverse of ``write_resume_indices_file``. Empty file → empty list."""
    if not source.is_file():
        return []
    out: list[int] = []
    for line in source.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        out.append(int(line))
    return out
