# Result Artifacts

`benchmark_runs_generations.7z.001` through `.013` contain the archived generation and evaluation result files selected from `benchmark_runs/`:

- `raw/` and `clean/` generation JSONL outputs
- `summary.json`
- judge metrics
- judge solution JSONL files
- generation/evaluation logs

The archive is split into sub-100MB volumes for GitHub compatibility. Extract from the first volume:

```bash
7z x artifacts/benchmark_runs_generations.7z.001
```

`benchmark_runs_archive_files.txt` lists the files included in the archive.

## 2026-06-29 refresh

`benchmark_runs_generations.7z.*` above was captured on 2026-05-08 and does not
include runs produced afterward. `benchmark_runs_results_20260629.7z.001` is a
fresh snapshot of every result file (`*.jsonl` generations, `*.csv` metrics,
`*.json` summaries, `*.log`) present in `benchmark_runs/` as of 2026-06-29 —
121 files, ~707 MB uncompressed, taken before the host MFS was wiped. The bulk
of `benchmark_runs/` (judge `*.in`/`*.out` test cases) is the re-downloadable
public CodeEditorBench judge dataset and is deliberately excluded.

```bash
7z x artifacts/benchmark_runs_results_20260629.7z.001
```

`benchmark_runs_results_20260629_files.txt` lists the files included.
