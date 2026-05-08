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
