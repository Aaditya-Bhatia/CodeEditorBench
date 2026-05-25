# Deprecated dirty deepseek-coder-6.7b-base run

Archived: 2026-05-25.

This run was generated on the k8s GPU pod against
`SFT_runs_same_size/model/deepseek-coder-6.7b-base_lora_7b_deepseek_coder_base_dirty_2026-04-22_11-49-45`
and produced unparseable output across all 3 benchmarks (CanItEdit /
HumanEvalFix / CodeEditorBench × 4 datasets), pass@1 = 0.00.

## Root cause (two compounding serve-side bugs)

1. **DeepSeek-Coder `<|EOT|>` (token 32021) not in stop set.** Stock
   `generation_config.json` only stops on 32014. Dirty-trained
   completions emit `<|EOT|>` at turn-end; vLLM ignores it and runs to
   `max_tokens` emitting learned garbage (literal `Ġ`/`Ċ` BPE
   byte-fallback chars and repeated `<|EOT|>` strings).
2. **`/v1/chat/completions` regression carryover** (HEF only,
   already-fixed). The May-11 HEF runner regression to chat-completions
   is archived separately under
   `human_eval_fix/backups/_archive_v1_chat_completion_2026-05-11/`. The
   May-20 retry of HEF dirty deepseek still failed because bug #1 was
   independent.

CanItEdit (`ChatAdaptorEditModel`) and CodeEditorBench
(`openai_compatible_inference.py`) also use chat completions, but for
models in `requires_simple_concat()` (deepseek-coder-6.7b-base is in
that list) the orchestrator overrides the chat template with
`chat_templates/simple_concat.jinja`, neutralizing the wrap.

## Evidence the adapter itself is fine

- Training loss 0.08, 342 steps, no NaN.
- `tokenizer.json` / `tokenizer_config.json` / `special_tokens_map.json`
  md5-identical to the working `_clean_` and `_unclean_` adapters.
- Same-size `_unclean_` adapter (same base, similar corpus, generated
  on the CPU box rather than the GPU pod) produced clean output:
  `import pandas as pd\nclass StringOperations:\n    """A class…"` —
  CanItEdit pass@1 = 34.62 (regenerated 2026-05-25, score in
  `results/same_size_results/same_size_canitedit.csv`).

## Fixes committed

- `Master_VLLM/serve.sh`: adds
  `--override-generation-config {eos_token_id:[32014,32021]}` for
  any `*deepseek-coder*` `MODEL_PATH`.
- `Master_VLLM/CLAUDE.md` § "DEV-POD ACTION REQUIRED": full regen
  recipe.
- `Master_VLLM/results/same_size_results/triage_status.md` § 1:
  detailed writeup with the 2026-05-14 incorrect diagnosis corrected.
- `Master_VLLM/results/same_size_results/generate_same_size_results.py`:
  `EXCLUDED_CELLS` renders the affected cells as `excluded`, not
  `0.00`, until regen lands.

## Re-generation

Tracked on the GPU pod via the orchestrator after pulling the patched
`serve.sh`. After regen and re-eval on the CPU box, drop the
`("deepseek-coder-6.7b-base", "dirty")` entry from `EXCLUDED_CELLS` and
re-run the generators.
