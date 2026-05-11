#!/usr/bin/env python3
"""Check CodeEditorBench generations for outputs above a token limit."""

from __future__ import annotations

import argparse
import csv
import json
import os
import re
import sys
from concurrent.futures import ProcessPoolExecutor, as_completed
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Iterable


DEFAULT_LIMIT = 2048
DEFAULT_RESULT_ROOTS = ("benchmark_runs",)
SKIP_DIR_NAMES = {"judge", "__pycache__"}
COMPLETION_FIELDS = ("code", "completion", "output", "response", "text")


@dataclass
class Violation:
    path: Path
    line_no: int
    run: str
    split: str
    dataset: str
    problem_id: object
    completion_id: object
    field: str
    item_index: int | None
    token_count: int
    char_count: int
    preview: str


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Scan CodeEditorBench JSONL generations and report any completion "
            "whose generated output exceeds the benchmark max_tokens limit."
        )
    )
    parser.add_argument(
        "paths",
        nargs="*",
        default=list(DEFAULT_RESULT_ROOTS),
        help="Files or directories to scan. Defaults to benchmark_runs/.",
    )
    parser.add_argument("--limit", type=int, default=DEFAULT_LIMIT, help="Token limit to enforce.")
    parser.add_argument(
        "--tokenizer",
        default=None,
        help=(
            "Hugging Face tokenizer name/path for exact model-token counts. "
            "Use the tokenizer for the model that generated the run."
        ),
    )
    parser.add_argument(
        "--approx",
        action="store_true",
        help=(
            "Allow an approximate built-in counter when --tokenizer is omitted. "
            "This is useful for triage, not for final audit evidence."
        ),
    )
    parser.add_argument(
        "--scope",
        choices=("raw", "clean", "all"),
        default="raw",
        help="Which benchmark_runs outputs to scan. Default: raw.",
    )
    parser.add_argument(
        "--output",
        default=None,
        help="Optional CSV path for the violation report.",
    )
    parser.add_argument(
        "--all-counts",
        default=None,
        help="Optional CSV path containing every counted sample, not just violations.",
    )
    parser.add_argument(
        "--fail-on-error",
        action="store_true",
        help="Exit nonzero if any JSONL files could not be parsed/read.",
    )
    parser.add_argument(
        "--workers",
        type=int,
        default=1,
        help=(
            "Number of worker processes for --approx scans. Use 0 to select "
            "the machine CPU count. Exact --tokenizer scans currently run serially."
        ),
    )
    return parser.parse_args()


def load_counter(args: argparse.Namespace) -> tuple[Callable[[str], int], str]:
    if args.tokenizer:
        try:
            from transformers import AutoTokenizer
        except ImportError as exc:
            raise SystemExit(
                "transformers is required for --tokenizer. Install it or rerun with --approx."
            ) from exc

        tokenizer = AutoTokenizer.from_pretrained(args.tokenizer, trust_remote_code=True)

        def count_tokens(text: str) -> int:
            return len(tokenizer.encode(text, add_special_tokens=False))

        return count_tokens, f"transformers:{args.tokenizer}"

    if not args.approx:
        raise SystemExit(
            "Refusing to produce token-limit audit without a tokenizer. "
            "Pass --tokenizer <model-or-tokenizer-path> for exact counts, or --approx for triage."
        )

    token_re = re.compile(r"\w+|[^\w\s]", re.UNICODE)

    def approximate_count(text: str) -> int:
        return len(token_re.findall(text))

    return approximate_count, "approx-regex"


def should_skip_dir(path: Path) -> bool:
    return path.name in SKIP_DIR_NAMES


def iter_jsonl_files(paths: Iterable[str], scope: str) -> Iterable[Path]:
    for raw_path in paths:
        path = Path(raw_path)
        if path.is_file():
            if path.suffix == ".jsonl":
                yield path
            continue
        if not path.exists():
            print(f"[WARN] Missing path: {path}", file=sys.stderr)
            continue
        for candidate in path.rglob("*.jsonl"):
            parts = set(candidate.parts)
            if any(part in SKIP_DIR_NAMES for part in parts):
                continue
            if scope != "all":
                if "benchmark_runs" in candidate.parts and scope not in candidate.parts:
                    continue
            yield candidate


def infer_location(path: Path) -> tuple[str, str, str]:
    parts = path.parts
    run = ""
    split = ""
    dataset = ""
    if "benchmark_runs" in parts:
        idx = parts.index("benchmark_runs")
        if idx + 1 < len(parts):
            run = parts[idx + 1]
        if idx + 2 < len(parts):
            split = parts[idx + 2]
        if idx + 3 < len(parts):
            dataset = parts[idx + 3]
    else:
        for part in parts:
            if part.startswith("code_"):
                dataset = part
                break
    return run, split, dataset


def normalize_completion(value: object) -> list[tuple[int | None, str]]:
    if isinstance(value, str):
        return [(None, value)]
    if isinstance(value, list):
        items: list[tuple[int | None, str]] = []
        for index, item in enumerate(value):
            if isinstance(item, str):
                items.append((index, item))
            elif item is not None:
                items.append((index, json.dumps(item, ensure_ascii=False)))
        return items
    if value is None:
        return []
    return [(None, json.dumps(value, ensure_ascii=False))]


def iter_record_completions(record: dict) -> Iterable[tuple[str, int | None, str]]:
    for field in COMPLETION_FIELDS:
        if field in record:
            for item_index, text in normalize_completion(record[field]):
                yield field, item_index, text
            return


def preview_text(text: str, width: int = 120) -> str:
    return re.sub(r"\s+", " ", text).strip()[:width]


def write_csv(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = [
        "token_count",
        "char_count",
        "limit",
        "path",
        "line_no",
        "run",
        "split",
        "dataset",
        "problem_id",
        "completion_id",
        "field",
        "item_index",
        "preview",
    ]
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def scan_file_approx(path: Path, limit: int, include_all_counts: bool) -> dict:
    token_re = re.compile(r"\w+|[^\w\s]", re.UNICODE)
    run, split, dataset = infer_location(path)
    violations: list[dict] = []
    all_rows: list[dict] = []
    scanned_records = 0
    counted_samples = 0
    errors = 0

    def approximate_count(text: str) -> int:
        return len(token_re.findall(text))

    try:
        handle = path.open("r", encoding="utf-8")
    except OSError as exc:
        return {
            "violations": violations,
            "all_rows": all_rows,
            "scanned_records": scanned_records,
            "counted_samples": counted_samples,
            "errors": 1,
            "warnings": [f"[WARN] Could not read {path}: {exc}"],
        }

    warnings: list[str] = []
    with handle:
        for line_no, line in enumerate(handle, start=1):
            line = line.strip()
            if not line:
                continue
            try:
                record = json.loads(line)
            except json.JSONDecodeError as exc:
                errors += 1
                warnings.append(f"[WARN] Invalid JSON {path}:{line_no}: {exc}")
                continue
            if not isinstance(record, dict):
                continue
            found_completion = False
            for field, item_index, text in iter_record_completions(record):
                found_completion = True
                token_count = approximate_count(text)
                counted_samples += 1
                row = {
                    "token_count": token_count,
                    "char_count": len(text),
                    "limit": limit,
                    "path": str(path),
                    "line_no": line_no,
                    "run": run,
                    "split": split,
                    "dataset": dataset,
                    "problem_id": record.get("problem_id", ""),
                    "completion_id": record.get("completion_id", ""),
                    "field": field,
                    "item_index": "" if item_index is None else item_index,
                    "preview": preview_text(text),
                }
                if include_all_counts:
                    all_rows.append(row)
                if token_count > limit:
                    violations.append(row)
            if found_completion:
                scanned_records += 1

    return {
        "violations": violations,
        "all_rows": all_rows,
        "scanned_records": scanned_records,
        "counted_samples": counted_samples,
        "errors": errors,
        "warnings": warnings,
    }


def main() -> int:
    args = parse_args()
    count_tokens, counter_name = load_counter(args)

    files = sorted(set(iter_jsonl_files(args.paths, args.scope)))
    if not files:
        print("No JSONL files found.", file=sys.stderr)
        return 2

    violations: list[Violation] = []
    all_rows: list[dict] = []
    scanned_records = 0
    counted_samples = 0
    errors = 0

    if args.approx and not args.tokenizer and args.workers != 1:
        workers = os.cpu_count() or 1 if args.workers == 0 else args.workers
        workers = max(1, workers)
        with ProcessPoolExecutor(max_workers=workers) as executor:
            futures = [
                executor.submit(scan_file_approx, path, args.limit, bool(args.all_counts))
                for path in files
            ]
            for future in as_completed(futures):
                result = future.result()
                for warning in result["warnings"]:
                    print(warning, file=sys.stderr)
                violation_rows = result["violations"]
                violations.extend(
                    Violation(
                        path=Path(row["path"]),
                        line_no=row["line_no"],
                        run=row["run"],
                        split=row["split"],
                        dataset=row["dataset"],
                        problem_id=row["problem_id"],
                        completion_id=row["completion_id"],
                        field=row["field"],
                        item_index=None if row["item_index"] == "" else row["item_index"],
                        token_count=row["token_count"],
                        char_count=row["char_count"],
                        preview=row["preview"],
                    )
                    for row in violation_rows
                )
                if args.all_counts:
                    all_rows.extend(result["all_rows"])
                scanned_records += result["scanned_records"]
                counted_samples += result["counted_samples"]
                errors += result["errors"]

        violation_rows = [
            {
                "token_count": violation.token_count,
                "char_count": violation.char_count,
                "limit": args.limit,
                "path": str(violation.path),
                "line_no": violation.line_no,
                "run": violation.run,
                "split": violation.split,
                "dataset": violation.dataset,
                "problem_id": violation.problem_id,
                "completion_id": violation.completion_id,
                "field": violation.field,
                "item_index": "" if violation.item_index is None else violation.item_index,
                "preview": violation.preview,
            }
            for violation in sorted(violations, key=lambda item: item.token_count, reverse=True)
        ]

        if args.output:
            write_csv(Path(args.output), violation_rows)
        if args.all_counts:
            write_csv(Path(args.all_counts), all_rows)

        print(f"Counter: {counter_name}")
        print(f"Limit: {args.limit}")
        print(f"Files scanned: {len(files)}")
        print(f"Records with completions: {scanned_records}")
        print(f"Completions counted: {counted_samples}")
        print(f"Violations: {len(violations)}")
        print(f"Workers: {workers}")
        if args.output:
            print(f"Violation report: {args.output}")
        if args.all_counts:
            print(f"All-counts report: {args.all_counts}")

        for violation in sorted(violations, key=lambda item: item.token_count, reverse=True)[:20]:
            item_suffix = "" if violation.item_index is None else f"[{violation.item_index}]"
            print(
                f"{violation.token_count:>6} tokens | {violation.path}:{violation.line_no} | "
                f"problem_id={violation.problem_id} completion_id={violation.completion_id} "
                f"{violation.field}{item_suffix}"
            )

        if errors and args.fail_on_error:
            return 3
        return 1 if violations else 0

    for path in files:
        run, split, dataset = infer_location(path)
        try:
            handle = path.open("r", encoding="utf-8")
        except OSError as exc:
            errors += 1
            print(f"[WARN] Could not read {path}: {exc}", file=sys.stderr)
            continue

        with handle:
            for line_no, line in enumerate(handle, start=1):
                line = line.strip()
                if not line:
                    continue
                try:
                    record = json.loads(line)
                except json.JSONDecodeError as exc:
                    errors += 1
                    print(f"[WARN] Invalid JSON {path}:{line_no}: {exc}", file=sys.stderr)
                    continue
                if not isinstance(record, dict):
                    continue
                found_completion = False
                for field, item_index, text in iter_record_completions(record):
                    found_completion = True
                    token_count = count_tokens(text)
                    counted_samples += 1
                    row = {
                        "token_count": token_count,
                        "char_count": len(text),
                        "limit": args.limit,
                        "path": str(path),
                        "line_no": line_no,
                        "run": run,
                        "split": split,
                        "dataset": dataset,
                        "problem_id": record.get("problem_id", ""),
                        "completion_id": record.get("completion_id", ""),
                        "field": field,
                        "item_index": "" if item_index is None else item_index,
                        "preview": preview_text(text),
                    }
                    if args.all_counts:
                        all_rows.append(row)
                    if token_count > args.limit:
                        violations.append(
                            Violation(
                                path=path,
                                line_no=line_no,
                                run=run,
                                split=split,
                                dataset=dataset,
                                problem_id=record.get("problem_id", ""),
                                completion_id=record.get("completion_id", ""),
                                field=field,
                                item_index=item_index,
                                token_count=token_count,
                                char_count=len(text),
                                preview=preview_text(text),
                            )
                        )
                if found_completion:
                    scanned_records += 1

    violation_rows = [
        {
            "token_count": violation.token_count,
            "char_count": violation.char_count,
            "limit": args.limit,
            "path": str(violation.path),
            "line_no": violation.line_no,
            "run": violation.run,
            "split": violation.split,
            "dataset": violation.dataset,
            "problem_id": violation.problem_id,
            "completion_id": violation.completion_id,
            "field": violation.field,
            "item_index": "" if violation.item_index is None else violation.item_index,
            "preview": violation.preview,
        }
        for violation in sorted(violations, key=lambda item: item.token_count, reverse=True)
    ]

    if args.output:
        write_csv(Path(args.output), violation_rows)
    if args.all_counts:
        write_csv(Path(args.all_counts), all_rows)

    print(f"Counter: {counter_name}")
    print(f"Limit: {args.limit}")
    print(f"Files scanned: {len(files)}")
    print(f"Records with completions: {scanned_records}")
    print(f"Completions counted: {counted_samples}")
    print(f"Violations: {len(violations)}")
    if args.output:
        print(f"Violation report: {args.output}")
    if args.all_counts:
        print(f"All-counts report: {args.all_counts}")

    for violation in sorted(violations, key=lambda item: item.token_count, reverse=True)[:20]:
        item_suffix = "" if violation.item_index is None else f"[{violation.item_index}]"
        print(
            f"{violation.token_count:>6} tokens | {violation.path}:{violation.line_no} | "
            f"problem_id={violation.problem_id} completion_id={violation.completion_id} "
            f"{violation.field}{item_suffix}"
        )

    if errors and args.fail_on_error:
        return 3
    return 1 if violations else 0


if __name__ == "__main__":
    raise SystemExit(main())
