# CodeEditorBench Benchmark-Run Backups

This directory holds per-run `tar.gz` archives of canonical CEB runs
plus any cherry-picked quarantine runs we chose to preserve. Each
archive expands into a single run dir under
`<repo>/benchmark_runs/<run-name>/`.

## What's inside each `<run>.tar.gz`

```
<run-name>/
├── summary.json                          ← state + eval_status counts
├── raw/
│   ├── code_debug/<...>.jsonl            ← the 4 dataset generation files
│   ├── code_translate/<...>.jsonl        (PLAIN JSONL — line 1 is config header)
│   ├── code_polishment/<...>.jsonl
│   └── code_switch/<...>.jsonl
└── judge/
    └── metrics/
        ├── metrics_primary.csv           ← per-dataset acceptance rates
        └── metrics_*.csv
```

The judge's per-submission HUSTOJ artifacts (`judge/run*/`),
container logs (`judge/log/`), submitted solutions
(`judge/solution_folder/`), helper scripts (`judge/scripts/`), and
the derived `clean/` text — none of those are in the tarball. They
are either root-owned, regenerable from `raw/`, or not needed for
result reporting.

## Quick-start: restore on a fresh machine

```bash
git clone git@github.com:Aaditya-Bhatia/CodeEditorBench.git
cd CodeEditorBench

# Restore one run
mkdir -p benchmark_runs
tar -xzf backups/<run-name>.tar.gz -C benchmark_runs/

# Restore everything (paired with the Master_VLLM extract script)
python3 /path/to/Master_VLLM/scripts/backup_extract.py --repo-root .
```

If you're on a machine with different paths than the original CPU
host, also rewrite the paths embedded in `summary.json`:

```bash
python3 /path/to/Master_VLLM/scripts/backup_extract.py --repo-root . \
  --rewrite-paths-from /shared_workspace_mfs/aadi/Projects \
  --rewrite-paths-to   /your/local/Projects
```

## Adding a new run to the backup

```bash
cd /path/to/Master_VLLM
python3 scripts/backup_compress.py --include-quarantine --execute --only-benchmark CodeEditorBench
cd /path/to/CodeEditorBench
git add backups/<new-run>.tar.gz backups/INDEX.csv
git commit -m "Back up <model>-<variant> CEB run"
git push origin main
```

## INDEX.csv

`INDEX.csv` carries one row per tarball with run name, model, variant,
file count, raw on-disk size, and compressed tarball size. Use it as
a quick searchable catalog. The bench's verdict counts live in each
run's `judge/metrics/metrics_primary.csv` (extract first).

## See also

- **Operational protocol (read first):** `Master_VLLM/.claude/agents/cross-repo-backup-protocol.md` — the single source of truth for commit/pull/recovery across both hosts.
- Tarball format reference: `Master_VLLM/docs/BACKUP_LAYOUT.md`
- Cross-repo layout + path-drift handling: `Master_VLLM/docs/repo_layout.md`
- Run-classification rules (same-size vs different-size): `Master_VLLM/.claude/agents/results-pipeline-guide.md`
