# Max Token Mishap Audit

Generated on 2026-05-11 from raw CodeEditorBench benchmark outputs.

The benchmark-defined generation limit being checked is `2048` tokens. This
audit used the approximate regex counter from `check_max_tokens.py`, so the
large over-limit cases are strong triage evidence, but exact evidence should be
rerun per model with the matching Hugging Face tokenizer.

## Reports

- `check_max_tokens.py`: scanner used to produce the reports.
- `max_token_violations_all_raw_approx.csv.gz`: every raw completion sample
  above the `2048` approximate-token limit.
- `max_token_counts_all_raw_approx.csv.gz`: every counted raw completion
  sample, including non-violations.
- `max_token_violation_files_raw_approx.txt`: all files with at least one
  violation.
- `max_token_violation_files_summary_raw_approx.csv`: per-file violation count,
  max token count, and median token count among violating samples.

## Summary

- Files scanned: `614`
- Completion samples scanned: `1,195,937`
- Samples over `2048`: `541,612`
- Files with at least one violation: `560`
- Runs with at least one violation: `153`
- One malformed JSONL line was skipped:
  `benchmark_runs/codellama-13b-hf-lora-unclean74k-20260416T235008836128Z/raw/code_polishment/codellama_13b_hf_lora_unclean74k_20260416T235008836128Z_0_end.jsonl:1940`

## Distribution

| Approx tokens | Samples |
| --- | ---: |
| `2049-2500` | `12,380` |
| `2501-3000` | `10,469` |
| `3001-4096` | `216,072` |
| `4097-8192` | `299,865` |
| `8193-12000` | `1,450` |
| `12001-16000` | `1,160` |
| `16001-20000` | `207` |
| `>20000` | `9` |

Quantiles among violating samples:

- p50: `4175`
- p75: `4603`
- p90: `5881`
- p95: `6048`
- p99: `8058`
- max: `24525`

## Qualitative Inspection

The worst samples look like runaway generation rather than legitimate long
answers. Common patterns include:

- thousands of repeated `"""", """", ...`
- repeated code fences/backticks
- huge runs of `+` characters
- a plausible answer at the start followed by repetitive junk until cutoff
- duplicated code blocks or partial loops

Example top offender: a `24525` approximate-token sample was mostly `+`
repetition after a short `canWinNim` answer. Several `20K` samples were a
valid-looking code answer followed by thousands of repeated `"""",` fragments.
