# CodeEditorBench Results

Scores are pass rates (%). Non-numeric values indicate run status.

### Debug

| Model                          | Size   | Type       |     Baseline |   Clean (10K) |   Dirty (10K) |   Unclean-74K |
| ------------------------------ | ------ | ---------- | -----------: | ------------: | ------------: | ------------: |
| qwen2.5-3B                     | 3B     | base       |         33.6 |          33.2 |          26.2 |          24.9 |
| qwen2.5-coder-7B               | 7B     | base       |          0.0 |          44.9 |          46.3 |          44.8 |
| qwen3-14B-base                 | 14B    | base       |         48.4 |          38.9 |          34.2 |          38.3 |

### Translate

| Model                          | Size   | Type       |     Baseline |   Clean (10K) |   Dirty (10K) |   Unclean-74K |
| ------------------------------ | ------ | ---------- | -----------: | ------------: | ------------: | ------------: |
| qwen2.5-3B                     | 3B     | base       |         29.5 |          28.0 |          29.1 |          31.6 |
| qwen2.5-coder-7B               | 7B     | base       |          0.0 |          38.6 |          36.7 |          36.8 |
| qwen3-14B-base                 | 14B    | base       |         46.4 |          45.6 |          37.6 |          45.5 |

### Switch

| Model                          | Size   | Type       |     Baseline |   Clean (10K) |   Dirty (10K) |   Unclean-74K |
| ------------------------------ | ------ | ---------- | -----------: | ------------: | ------------: | ------------: |
| qwen2.5-3B                     | 3B     | base       |          4.0 |           4.6 |           3.3 |           3.4 |
| qwen2.5-coder-7B               | 7B     | base       |          0.0 |          12.2 |          10.4 |          11.6 |
| qwen3-14B-base                 | 14B    | base       |         15.4 |          13.6 |          12.7 |          13.1 |

### Polish

| Model                          | Size   | Type       |     Baseline |   Clean (10K) |   Dirty (10K) |   Unclean-74K |
| ------------------------------ | ------ | ---------- | -----------: | ------------: | ------------: | ------------: |
| qwen2.5-3B                     | 3B     | base       |         22.7 |          23.0 |          26.5 |          30.1 |
| qwen2.5-coder-7B               | 7B     | base       |          0.1 |          16.8 |          35.1 |          34.6 |
| qwen3-14B-base                 | 14B    | base       |         27.0 |          34.3 |          25.4 |          35.9 |

### Average (all 4 metrics)

| Model                          | Size   | Type       |     Baseline |   Clean (10K) |   Dirty (10K) |   Unclean-74K |
| ------------------------------ | ------ | ---------- | -----------: | ------------: | ------------: | ------------: |
| qwen2.5-3B                     | 3B     | base       |         22.5 |          22.2 |          21.3 |          22.5 |
| qwen2.5-coder-7B               | 7B     | base       |          0.0 |          28.1 |          32.1 |          32.0 |
| qwen3-14B-base                 | 14B    | base       |         34.3 |          33.1 |          27.5 |          33.2 |

*3 models, 12/12 cells complete*
