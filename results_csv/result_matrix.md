# CodeEditorBench Results

Scores are pass rates (%). Non-numeric values indicate run status.

### Debug

| Model                          | Size   | Type       |     Baseline |        Clean |        Dirty |   Unclean-74K |
| ------------------------------ | ------ | ---------- | -----------: | -----------: | -----------: | ------------: |
| llama-3.2-3B                   | 3B     | base       |          5.0 |         23.7 |         21.2 |          12.5 |
| qwen2.5-3B                     | 3B     | base       |         33.6 |         26.9 |         25.2 |          24.9 |
| qwen2.5-coder-3B               | 3B     | base       |         42.1 |            — |            — |             — |
| starcoder2-3B                  | 3B     | base       |         10.5 |         24.5 |         23.6 |          24.6 |
| qwen3-4B-base                  | 4B     | base       |         45.3 |         43.2 |         35.8 |          23.6 |
| deepseek-coder-6.7B-base       | 6.7B   | base       |         31.9 |         31.5 |         39.4 |          41.7 |
| codellama-7B-hf                | 7B     | base       |          3.6 |         24.8 |         19.9 |          20.1 |
| qwen2.5-coder-7B               | 7B     | base       |          0.0 |         47.8 |         47.8 |          44.8 |
| starcoder2-7B                  | 7B     | base       |         30.4 |         34.8 |         30.0 |          29.7 |
| qwen3-8B-base                  | 8B     | base       |         47.0 |         20.8 |          0.1 |           7.1 |
| codellama-13B-hf               | 13B    | base       |          8.3 |         31.7 |         28.4 |          24.1 |
| qwen2.5-coder-14B              | 14B    | base       |          0.0 |         52.7 |         49.3 |          51.1 |
| qwen3-14B-base                 | 14B    | base       |         48.4 |         30.4 |         43.4 |          38.3 |
| starcoder2-15B                 | 15B    | base       |         36.2 |         42.7 |         41.0 |          43.1 |
|                                |        |            |              |              |              |               |
| qwen2.5-coder-3B-instruct      | 3B     | instruct   |         38.9 |         40.7 |         30.3 |          29.2 |
| deepseek-coder-6.7B-instruct   | 6.7B   | instruct   |         41.7 |         31.8 |         38.9 |          38.9 |
| qwen2.5-coder-7B-instruct      | 7B     | instruct   |         44.2 |         46.0 |         41.7 |          43.1 |
| qwen2.5-coder-14B-instruct     | 14B    | instruct   |         49.1 |         52.0 |         49.4 |          49.4 |

### Translate

| Model                          | Size   | Type       |     Baseline |        Clean |        Dirty |   Unclean-74K |
| ------------------------------ | ------ | ---------- | -----------: | -----------: | -----------: | ------------: |
| llama-3.2-3B                   | 3B     | base       |         20.2 |         18.7 |         18.4 |          15.9 |
| qwen2.5-3B                     | 3B     | base       |         29.5 |         55.3 |         28.9 |          31.6 |
| qwen2.5-coder-3B               | 3B     | base       |         34.8 |            — |            — |             — |
| starcoder2-3B                  | 3B     | base       |         25.7 |         26.1 |         26.8 |          23.5 |
| qwen3-4B-base                  | 4B     | base       |         35.4 |         35.9 |         31.8 |          34.7 |
| deepseek-coder-6.7B-base       | 6.7B   | base       |         31.1 |         41.5 |         36.8 |          39.0 |
| codellama-7B-hf                | 7B     | base       |         18.9 |         23.1 |         20.9 |          21.8 |
| qwen2.5-coder-7B               | 7B     | base       |          0.0 |         40.6 |         36.1 |          36.8 |
| starcoder2-7B                  | 7B     | base       |         30.0 |         32.3 |         30.6 |          30.9 |
| qwen3-8B-base                  | 8B     | base       |         40.8 |         18.8 |          0.0 |           2.9 |
| codellama-13B-hf               | 13B    | base       |         28.1 |         33.5 |         27.0 |          27.5 |
| qwen2.5-coder-14B              | 14B    | base       |          0.0 |         49.1 |         40.5 |          47.2 |
| qwen3-14B-base                 | 14B    | base       |         46.4 |         43.6 |         39.2 |          45.5 |
| starcoder2-15B                 | 15B    | base       |         42.4 |         37.5 |         36.8 |          39.7 |
|                                |        |            |              |              |              |               |
| qwen2.5-coder-3B-instruct      | 3B     | instruct   |         29.0 |         37.5 |         23.4 |          24.9 |
| deepseek-coder-6.7B-instruct   | 6.7B   | instruct   |         38.2 |         40.4 |         38.1 |          37.8 |
| qwen2.5-coder-7B-instruct      | 7B     | instruct   |         43.0 |         40.8 |         36.3 |          37.5 |
| qwen2.5-coder-14B-instruct     | 14B    | instruct   |         46.7 |         49.1 |         46.9 |          46.9 |

### Switch

| Model                          | Size   | Type       |     Baseline |        Clean |        Dirty |   Unclean-74K |
| ------------------------------ | ------ | ---------- | -----------: | -----------: | -----------: | ------------: |
| llama-3.2-3B                   | 3B     | base       |          1.6 |          1.7 |          1.2 |           1.4 |
| qwen2.5-3B                     | 3B     | base       |          4.0 |          1.9 |          3.4 |           3.4 |
| qwen2.5-coder-3B               | 3B     | base       |          9.0 |            — |            — |             — |
| starcoder2-3B                  | 3B     | base       |          2.4 |          2.6 |          2.1 |           2.3 |
| qwen3-4B-base                  | 4B     | base       |          9.4 |          7.3 |          7.5 |           7.6 |
| deepseek-coder-6.7B-base       | 6.7B   | base       |         10.3 |          9.6 |          9.7 |          10.4 |
| codellama-7B-hf                | 7B     | base       |          3.4 |          2.2 |          3.7 |           3.4 |
| qwen2.5-coder-7B               | 7B     | base       |          0.0 |         13.0 |         11.6 |          11.6 |
| starcoder2-7B                  | 7B     | base       |          3.2 |          3.2 |          3.6 |           4.1 |
| qwen3-8B-base                  | 8B     | base       |         12.9 |          6.0 |          0.0 |           1.0 |
| codellama-13B-hf               | 13B    | base       |          5.1 |          4.6 |          4.3 |           3.2 |
| qwen2.5-coder-14B              | 14B    | base       |          0.0 |         17.1 |         13.6 |          15.2 |
| qwen3-14B-base                 | 14B    | base       |         15.4 |         13.2 |         11.2 |          13.1 |
| starcoder2-15B                 | 15B    | base       |          6.0 |          8.4 |          6.8 |           8.1 |
|                                |        |            |              |              |              |               |
| qwen2.5-coder-3B-instruct      | 3B     | instruct   |          8.6 |          9.6 |          2.5 |           3.6 |
| deepseek-coder-6.7B-instruct   | 6.7B   | instruct   |         13.9 |         11.0 |          9.9 |          10.2 |
| qwen2.5-coder-7B-instruct      | 7B     | instruct   |         15.2 |         13.5 |         13.0 |          12.8 |
| qwen2.5-coder-14B-instruct     | 14B    | instruct   |         16.3 |         17.2 |         15.2 |          16.0 |

### Polish

| Model                          | Size   | Type       |     Baseline |        Clean |        Dirty |   Unclean-74K |
| ------------------------------ | ------ | ---------- | -----------: | -----------: | -----------: | ------------: |
| llama-3.2-3B                   | 3B     | base       |         52.9 |         34.8 |         32.0 |          34.8 |
| qwen2.5-3B                     | 3B     | base       |         22.7 |         54.4 |         24.4 |          30.1 |
| qwen2.5-coder-3B               | 3B     | base       |         40.3 |            — |            — |             — |
| starcoder2-3B                  | 3B     | base       |         21.7 |         28.9 |         31.0 |          31.0 |
| qwen3-4B-base                  | 4B     | base       |         25.0 |         27.1 |         26.3 |          35.0 |
| deepseek-coder-6.7B-base       | 6.7B   | base       |         35.3 |         36.1 |         40.0 |          38.3 |
| codellama-7B-hf                | 7B     | base       |         30.8 |         22.6 |         42.2 |          36.0 |
| qwen2.5-coder-7B               | 7B     | base       |          0.1 |         21.7 |         64.8 |          34.6 |
| starcoder2-7B                  | 7B     | base       |         42.2 |         30.9 |         30.6 |          55.1 |
| qwen3-8B-base                  | 8B     | base       |         27.0 |         11.8 |          0.1 |           5.0 |
| codellama-13B-hf               | 13B    | base       |         30.7 |         23.2 |         32.2 |          27.3 |
| qwen2.5-coder-14B              | 14B    | base       |          0.0 |         38.1 |         35.6 |          63.0 |
| qwen3-14B-base                 | 14B    | base       |         27.0 |         44.7 |         33.9 |          35.9 |
| starcoder2-15B                 | 15B    | base       |         29.6 |         27.0 |         32.5 |          47.7 |
|                                |        |            |              |              |              |               |
| qwen2.5-coder-3B-instruct      | 3B     | instruct   |         23.0 |         25.7 |         17.0 |          17.3 |
| deepseek-coder-6.7B-instruct   | 6.7B   | instruct   |         21.6 |         30.1 |         34.1 |          27.0 |
| qwen2.5-coder-7B-instruct      | 7B     | instruct   |         19.5 |         17.1 |         29.6 |          24.6 |
| qwen2.5-coder-14B-instruct     | 14B    | instruct   |         31.1 |         35.1 |         34.3 |          31.1 |

### Average (all 4 metrics)

| Model                          | Size   | Type       |     Baseline |        Clean |        Dirty |   Unclean-74K |
| ------------------------------ | ------ | ---------- | -----------: | -----------: | -----------: | ------------: |
| llama-3.2-3B                   | 3B     | base       |         19.9 |         19.7 |         18.2 |          16.1 |
| qwen2.5-3B                     | 3B     | base       |         22.5 |         34.6 |         20.5 |          22.5 |
| qwen2.5-coder-3B               | 3B     | base       |         31.5 |            — |            — |             — |
| starcoder2-3B                  | 3B     | base       |         15.1 |         20.6 |         20.9 |          20.4 |
| qwen3-4B-base                  | 4B     | base       |         28.8 |         28.4 |         25.4 |          25.2 |
| deepseek-coder-6.7B-base       | 6.7B   | base       |         27.1 |         29.7 |         31.5 |          32.3 |
| codellama-7B-hf                | 7B     | base       |         14.2 |         18.2 |         21.6 |          20.3 |
| qwen2.5-coder-7B               | 7B     | base       |          0.0 |         30.8 |         40.1 |          32.0 |
| starcoder2-7B                  | 7B     | base       |         26.5 |         25.3 |         23.7 |          30.0 |
| qwen3-8B-base                  | 8B     | base       |         31.9 |         14.4 |          0.1 |           4.0 |
| codellama-13B-hf               | 13B    | base       |         18.0 |         23.2 |         23.0 |          20.6 |
| qwen2.5-coder-14B              | 14B    | base       |          0.0 |         39.3 |         34.8 |          44.1 |
| qwen3-14B-base                 | 14B    | base       |         34.3 |         33.0 |         31.9 |          33.2 |
| starcoder2-15B                 | 15B    | base       |         28.5 |         28.9 |         29.3 |          34.6 |
|                                |        |            |              |              |              |               |
| qwen2.5-coder-3B-instruct      | 3B     | instruct   |         24.9 |         28.4 |         18.3 |          18.7 |
| deepseek-coder-6.7B-instruct   | 6.7B   | instruct   |         28.9 |         28.3 |         30.2 |          28.5 |
| qwen2.5-coder-7B-instruct      | 7B     | instruct   |         30.5 |         29.3 |         30.2 |          29.5 |
| qwen2.5-coder-14B-instruct     | 14B    | instruct   |         35.8 |         38.3 |         36.5 |          35.8 |

*18 models, 69/72 cells complete*
