"""Tests for resume_helpers.py.

These tests use only the stdlib and are designed to run without any of CEB's
heavy dependencies (torch, vllm, jsonlines). To run them directly:

    cd /workspace/CodeEditorBench/scripts && python -m unittest test_resume_helpers

or via pytest:

    pytest /workspace/CodeEditorBench/scripts/test_resume_helpers.py
"""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

import resume_helpers as rh


def _write_jsonl(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as fh:
        for row in rows:
            fh.write(json.dumps(row) + "\n")


class InputDatasetProblemIdsTests(unittest.TestCase):
    def test_returns_idx_field_in_file_order(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "code_translate_primary.jsonl"
            _write_jsonl(
                path,
                [
                    {"idx": 1, "title": "a"},
                    {"idx": 2, "title": "b"},
                    {"idx": 3, "title": "c"},
                ],
            )
            self.assertEqual(rh.input_dataset_problem_ids(path), [1, 2, 3])

    def test_falls_back_to_position_when_idx_missing(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "input.jsonl"
            _write_jsonl(path, [{"title": "a"}, {"title": "b"}])
            self.assertEqual(rh.input_dataset_problem_ids(path), [0, 1])


class WrittenProblemIdsTests(unittest.TestCase):
    def test_skips_metadata_header_row(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "out.jsonl"
            _write_jsonl(
                path,
                [
                    # Header row (no problem_id, just config fields).
                    {"model": "x", "temperature": 0.0},
                    {"problem_id": 1, "code": "..."},
                    {"problem_id": 3, "code": "..."},
                ],
            )
            self.assertEqual(rh.written_problem_ids(path), {1, 3})

    def test_missing_file_returns_empty(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            self.assertEqual(rh.written_problem_ids(Path(tmp) / "missing.jsonl"), set())

    def test_malformed_lines_are_ignored(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "out.jsonl"
            path.write_text(
                json.dumps({"model": "x"}) + "\n"
                + "not json at all\n"
                + json.dumps({"problem_id": 5}) + "\n",
                encoding="utf-8",
            )
            # The corrupt line is silently skipped; idx 5 still recovered.
            self.assertEqual(rh.written_problem_ids(path), {5})


class MissingPositionsTests(unittest.TestCase):
    def test_returns_zero_based_positions_of_holes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            input_path = Path(tmp) / "input.jsonl"
            raw_path = Path(tmp) / "raw.jsonl"
            _write_jsonl(
                input_path,
                [{"idx": pid} for pid in [1, 2, 3, 4, 5]],
            )
            _write_jsonl(
                raw_path,
                [
                    {"model": "x"},  # metadata header
                    {"problem_id": 1},
                    {"problem_id": 3},
                    {"problem_id": 5},
                ],
            )
            # Missing problem_ids {2, 4} map to list positions [1, 3]
            # (the input list is 0-indexed; idx=1 is at position 0).
            self.assertEqual(rh.missing_positions(input_path, raw_path), [1, 3])

    def test_no_raw_file_means_everything_missing(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            input_path = Path(tmp) / "input.jsonl"
            _write_jsonl(input_path, [{"idx": 1}, {"idx": 2}, {"idx": 3}])
            self.assertEqual(
                rh.missing_positions(input_path, Path(tmp) / "missing.jsonl"),
                [0, 1, 2],
            )

    def test_returns_empty_when_all_written(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            input_path = Path(tmp) / "input.jsonl"
            raw_path = Path(tmp) / "raw.jsonl"
            _write_jsonl(input_path, [{"idx": 1}, {"idx": 2}])
            _write_jsonl(
                raw_path,
                [
                    {"model": "x"},
                    {"problem_id": 1},
                    {"problem_id": 2},
                ],
            )
            self.assertEqual(rh.missing_positions(input_path, raw_path), [])


class IndicesFileRoundTripTests(unittest.TestCase):
    def test_write_then_read_round_trips(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "resume.indices"
            rh.write_resume_indices_file([0, 3, 17, 42], target)
            self.assertEqual(rh.read_resume_indices_file(target), [0, 3, 17, 42])

    def test_empty_list_round_trips(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "resume.indices"
            rh.write_resume_indices_file([], target)
            self.assertEqual(rh.read_resume_indices_file(target), [])


if __name__ == "__main__":
    unittest.main()
