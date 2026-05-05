#!/usr/bin/env python3
"""Show CodeEditorBench results as a model x ablation matrix.

Each ablation shows 4 individual metric columns (Debug, Translate, Switch, Polish).
Base models first (sorted by size), then instruct models (sorted by size).
"""

import csv
import json
import re
from collections import defaultdict
from datetime import datetime
from pathlib import Path

BENCHMARK_DIR = Path(__file__).parent / "benchmark_runs"

# Main experiment
ABLATIONS = {
    "baseline":    ["baseline"],
    "clean":       ["lora-clean"],
    "dirty":       ["lora-dirty"],
    "unclean74k":  ["lora-unclean74k"],
}
ABLATION_DISPLAY = {
    "baseline": "Baseline",
    "clean": "Clean",
    "dirty": "Dirty",
    "unclean74k": "Unclean-74K",
}

METRICS = ["code_debug", "code_translation", "code_requirement_switch", "code_polishment"]
METRIC_SHORT = {"code_debug": "Debug", "code_translation": "Translate",
                "code_requirement_switch": "Switch", "code_polishment": "Polish"}


def parse_run_name(dirname, ablation_map):
    for abl_key, patterns in ablation_map.items():
        for pattern in patterns:
            marker = f"-{pattern}-"
            idx = dirname.find(marker)
            if idx != -1:
                model = dirname[:idx]
                return model, abl_key
    return None, None


def extract_size(model_name):
    m = re.search(r'(\d+\.?\d*)b', model_name, re.IGNORECASE)
    if m:
        return float(m.group(1))
    return 0


def infer_model_type(model_name):
    if "instruct" in model_name.lower():
        return "instruct"
    return "base"


def pretty_model_name(model_name):
    parts = model_name.split("-")
    result = []
    for p in parts:
        if re.match(r'^\d+\.?\d*b$', p, re.IGNORECASE):
            result.append(p.upper())
        else:
            result.append(p)
    return "-".join(result)


def load_metrics_csv(csv_path):
    with open(csv_path) as f:
        reader = csv.DictReader(f)
        for row in reader:
            return {k: float(row[k]) for k in METRICS if k in row and row[k]}
    return None


def load_summary_status(summary_path):
    with open(summary_path) as f:
        return json.load(f).get("status", "unknown")


def load_summary(summary_path):
    with open(summary_path) as f:
        return json.load(f)


def parse_run_timestamp(name):
    match = re.search(r"-(\d{8}T\d{6}(?:\d+)?Z)$", name)
    if not match:
        return datetime.min
    raw = match.group(1)
    fmt = "%Y%m%dT%H%M%SZ" if len(raw) == 16 else "%Y%m%dT%H%M%S%fZ"
    return datetime.strptime(raw, fmt)


CLEAN_DATASETS = ["code_debug", "code_translate", "code_polishment", "code_switch"]
EXPECTED_LINES = {"code_debug": 1907, "code_translate": 2525, "code_polishment": 2077, "code_switch": 1451}
TOTAL_EXPECTED = sum(EXPECTED_LINES.values())


def compute_generation_pct(run_dir):
    total = 0
    found = False
    for ds in CLEAN_DATASETS:
        clean_dir = run_dir / "clean" / ds
        if not clean_dir.exists():
            continue
        for f in clean_dir.glob("*.jsonl"):
            found = True
            total += sum(1 for _ in open(f))
    if not found:
        return None
    return total / TOTAL_EXPECTED * 100


def compute_eval_pct(run_dir):
    summary_path = run_dir / "summary.json"
    if summary_path.exists():
        data = load_summary(summary_path)
        es = data.get("eval_status", {})
        total = es.get("total", 0)
        resolved = es.get("resolved", 0)
        if total > 0:
            return resolved / total * 100
    return None


def classify_status(status, summary):
    eval_status = summary.get("eval_status", {}) if summary else {}
    pending = eval_status.get("pending")
    if status == "eval_complete" and pending not in (None, 0):
        return "eval_partial"
    return status


def has_valid_metrics(record):
    return record.get("_has_metrics", False)


def candidate_key(record):
    return (record["run_timestamp"], record["run_name"])


def choose_record(current, candidate):
    if current is None:
        return candidate
    current_valid = has_valid_metrics(current)
    candidate_valid = has_valid_metrics(candidate)
    if candidate_valid != current_valid:
        return candidate if candidate_valid else current
    if candidate_key(candidate) >= candidate_key(current):
        return candidate
    return current


def gather(ablation_map, model_filter=None):
    results = defaultdict(dict)

    for entry in sorted(BENCHMARK_DIR.iterdir()):
        if not entry.is_dir() or entry.name.startswith("_"):
            continue
        model, ablation = parse_run_name(entry.name, ablation_map)
        if model is None:
            continue
        if model_filter is not None and model not in model_filter:
            continue

        summary_path = entry / "summary.json"
        summary = load_summary(summary_path) if summary_path.exists() else {}
        status = classify_status(summary.get("status", "unknown"), summary)

        record = {
            "status": status,
            "_has_metrics": False,
            "run_name": entry.name,
            "run_timestamp": parse_run_timestamp(entry.name),
        }
        record["generation_pct"] = compute_generation_pct(entry)
        record["eval_pct"] = compute_eval_pct(entry)

        csv_primary = entry / "judge" / "metrics" / "metrics_primary.csv"
        if csv_primary.exists() and status in ("eval_complete", "eval_partial"):
            m = load_metrics_csv(csv_primary)
            if m:
                record.update(m)
                record["_has_metrics"] = True

        results[model][ablation] = choose_record(results[model].get(ablation), record)

    return results


def metric_cell(rec, metric_key):
    """Return (display_string, has_value) for a single metric in a record."""
    if rec is None:
        return ("—", False)
    if rec.get("_has_metrics") and metric_key in rec:
        return (f"{rec[metric_key] * 100:.1f}", True)
    st = rec["status"]
    gen = rec.get("generation_pct")
    ev = rec.get("eval_pct")
    if st == "eval_complete":
        return ("eval_done", False)
    if st == "eval_partial":
        return ("eval_partial", False)
    if st == "generation_complete" or (gen is not None and gen >= 99.9):
        if ev is not None and ev > 0:
            return (f"eval {ev:.0f}%", False)
        return ("gen_done", False)
    if st == "eval_failed":
        return ("eval_fail", False)
    if gen is not None:
        return (f"gen {gen:.0f}%", False)
    return (st[:12], False)


def sort_key(model):
    return (0 if infer_model_type(model) == "base" else 1, extract_size(model), model)


def print_table(results, ablation_map, ablation_display, title=None):
    abl_keys = list(ablation_map.keys())
    models = sorted(results.keys(), key=sort_key)

    if not models:
        return

    if title:
        print()
        print(f"{'=' * 40}")
        print(f"  {title}")
        print(f"{'=' * 40}")

    model_w = 30
    size_w = 6
    type_w = 10
    met_w = 8

    header = f"{'Model':<{model_w}} {'Size':<{size_w}} {'Type':<{type_w}}"
    for ak in abl_keys:
        label = ablation_display[ak]
        span = met_w * 4
        header += f" {label:^{span}}"
    print(header)

    subheader = " " * (model_w + 1 + size_w + 1 + type_w)
    for _ in abl_keys:
        for mk in METRICS:
            subheader += f" {METRIC_SHORT[mk]:>{met_w}}"
    print(subheader)
    print("-" * len(subheader))

    prev_type = None
    for model in models:
        mtype = infer_model_type(model)
        if prev_type is not None and prev_type != mtype:
            print()
        prev_type = mtype

        size_val = extract_size(model)
        size_str = f"{size_val:g}B"
        row = f"{pretty_model_name(model):<{model_w}} {size_str:<{size_w}} {mtype:<{type_w}}"
        for ak in abl_keys:
            rec = results[model].get(ak)
            for mk in METRICS:
                val, _ = metric_cell(rec, mk)
                row += f" {val:>{met_w}}"
        print(row)

    total_cells = len(models) * len(abl_keys)
    done = sum(1 for m in models for a in abl_keys
               if results[m].get(a, {}).get("_has_metrics"))
    print(f"\nTotal models: {len(models)}  |  Cells: {done}/{total_cells} complete")


def save_csv(results, ablation_map, ablation_display, path):
    abl_keys = list(ablation_map.keys())
    models = sorted(results.keys(), key=sort_key)

    fieldnames = ["model", "size", "type"]
    for ak in abl_keys:
        label = ablation_display[ak]
        for mk in METRICS:
            fieldnames.append(f"{label}-{METRIC_SHORT[mk]}")

    rows = []
    prev_type = None
    for model in models:
        mtype = infer_model_type(model)
        if prev_type is not None and prev_type != mtype:
            rows.append({k: "" for k in fieldnames})
        prev_type = mtype

        size_val = extract_size(model)
        row = {
            "model": pretty_model_name(model),
            "size": f"{size_val:g}B",
            "type": mtype,
        }
        for ak in abl_keys:
            label = ablation_display[ak]
            rec = results[model].get(ak)
            for mk in METRICS:
                col = f"{label}-{METRIC_SHORT[mk]}"
                val, _ = metric_cell(rec, mk)
                row[col] = val
        rows.append(row)

    with open(path, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames)
        w.writeheader()
        w.writerows(rows)
    print(f"Saved CSV: {path}")


def _make_metric_table(results, ablation_map, ablation_display, models, metric_key, title):
    """Build a single markdown table for one metric (or average)."""
    abl_keys = list(ablation_map.keys())
    col_names = ["Model", "Size", "Type"] + [ablation_display[ak] for ak in abl_keys]
    col_widths = [30, 6, 10] + [max(12, len(ablation_display[ak]) + 2) for ak in abl_keys]

    def fmt_row(vals):
        parts = []
        for i, (v, w) in enumerate(zip(vals, col_widths)):
            parts.append(v.ljust(w) if i < 3 else v.rjust(w))
        return "| " + " | ".join(parts) + " |"

    lines = [f"### {title}", ""]
    lines.append(fmt_row(col_names))
    seps = ["-" * w if i < 3 else "-" * (w - 1) + ":" for i, w in enumerate(col_widths)]
    lines.append("| " + " | ".join(seps) + " |")

    prev_type = None
    for model in models:
        mtype = infer_model_type(model)
        if prev_type is not None and prev_type != mtype:
            lines.append("| " + " | ".join(" " * w for w in col_widths) + " |")
        prev_type = mtype

        size_val = extract_size(model)
        vals = [pretty_model_name(model), f"{size_val:g}B", mtype]
        for ak in abl_keys:
            rec = results[model].get(ak)
            if metric_key == "_average":
                if rec and rec.get("_has_metrics"):
                    metric_vals = [rec.get(m) for m in METRICS if m in rec]
                    if metric_vals:
                        avg = sum(metric_vals) / len(metric_vals)
                        vals.append(f"{avg * 100:.1f}")
                    else:
                        vals.append("—")
                else:
                    val, _ = metric_cell(rec, METRICS[0])
                    vals.append(val)
            else:
                val, _ = metric_cell(rec, metric_key)
                vals.append(val)
        lines.append(fmt_row(vals))

    return "\n".join(lines)


def save_markdown(results, ablation_map, ablation_display, path):
    models = sorted(results.keys(), key=sort_key)
    if not models:
        return

    sections = ["# CodeEditorBench Results", ""]
    sections.append("Scores are pass rates (%). Non-numeric values indicate run status.")
    sections.append("")

    for mk in METRICS:
        sections.append(_make_metric_table(
            results, ablation_map, ablation_display, models, mk,
            METRIC_SHORT[mk]))
        sections.append("")

    sections.append(_make_metric_table(
        results, ablation_map, ablation_display, models, "_average",
        "Average (all 4 metrics)"))
    sections.append("")

    total_cells = len(models) * len(ablation_map)
    done = sum(1 for m in models for a in ablation_map
               if results[m].get(a, {}).get("_has_metrics"))
    sections.append(f"*{len(models)} models, {done}/{total_cells} cells complete*")
    sections.append("")

    with open(path, "w") as f:
        f.write("\n".join(sections))
    print(f"Saved Markdown: {path}")


def main():
    out_dir = Path(__file__).parent / "results_csv"
    out_dir.mkdir(exist_ok=True)

    # Main experiment
    main_results = gather(ABLATIONS)
    print()
    print("CodeEditorBench — Result Matrix (individual metric pass rates)")
    print("Scores shown as percentages. Non-numeric = run status.")
    print_table(main_results, ABLATIONS, ABLATION_DISPLAY,
                title="MAIN RESULTS (Full Training Data)")
    save_csv(main_results, ABLATIONS, ABLATION_DISPLAY, out_dir / "result_matrix.csv")
    save_markdown(main_results, ABLATIONS, ABLATION_DISPLAY, out_dir / "result_matrix.md")



if __name__ == "__main__":
    main()
