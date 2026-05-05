# CodeEditorBench

<p align="center">
    <a href="https://codeeditorbench.github.io"><img src="https://img.shields.io/badge/🏠-Home Page-8A2BE2"></a>
    <a href="https://arxiv.org/pdf/2404.03543.pdf"><img src="https://img.shields.io/badge/Paper-Arxiv-red"></a>
    <a href="https://huggingface.co/datasets/m-a-p/CodeEditorBench"><img src="https://img.shields.io/badge/🤗%20Hugging%20Face-CodeEditorBench-yellow"></a>
    <a href="https://github.com/CodeEditorBench/CodeEditorBench/blob/main/LICENSE"><img src="https://img.shields.io/badge/LICENSE-Apache--2.0-green"></a>
</p>

CodeEditorBench evaluates code editing models across debugging, translation, polishing, and requirement-switch tasks.

## Canonical Docs

Operational instructions live in one place:

- [`OPERATIONS.md`](/shared_workspace_mfs/aadi/Projects/CodeEditorBench/OPERATIONS.md)

The smaller docs in this repo are only pointers.

## Quick Start

Environment:

```bash
bash install.sh codeeditorbench
conda activate codeeditorbench
```

Config-driven benchmark run:

```bash
python scripts/run_benchmark.py \
  /shared_workspace_mfs/aadi/Projects/EditBench_fork/configs/qwen3-14b-base-lora-dirty.yaml
```

That command runs generation on the host, launches detached Docker evaluation, and sends Telegram notifications when generation completes and when evaluation completes.

Operationally:
- generation now launches all four datasets in parallel by default
- each run gets its own isolated judge workspace and default container name
- evaluation can continue after generation finishes without the vLLM server
- saved generations under `benchmark_runs/<run_name>/` can be evaluated later

## Data

Place benchmark data under `data/`:

```text
data/code_debug_primary.jsonl
data/code_translate_primary.jsonl
data/code_polishment_primary.jsonl
data/code_switch_primary.jsonl
```

## Legacy / Manual Entry Points

Manual building blocks still exist:
- `openai_compatible_inference.py`
- `result_postprocess.py`
- `evaluation/run_judge_container.sh`

Use [`OPERATIONS.md`](/shared_workspace_mfs/aadi/Projects/CodeEditorBench/OPERATIONS.md) for the full workflow and troubleshooting details.

## Citation

```bibtex
@misc{guo2024codeeditorbench,
      title={CodeEditorBench: Evaluating Code Editing Capability of Large Language Models},
      author={Jiawei Guo and Ziming Li and Xueling Liu and Kaijing Ma and Tianyu Zheng and Zhouliang Yu and Ding Pan and Yizhi LI and Ruibo Liu and Yue Wang and Shuyue Guo and Xingwei Qu and Xiang Yue and Ge Zhang and Wenhu Chen and Jie Fu},
      year={2024},
      eprint={2404.03543},
      archivePrefix={arXiv},
      primaryClass={cs.SE}
}
```

## Acknowledgement

- [HUSTOJ](https://github.com/zhblue/hustoj)
- [EvalPlus](https://github.com/evalplus/evalplus/tree/master)
- [BigCode](https://github.com/bigcode-project/bigcode-evaluation-harness)
