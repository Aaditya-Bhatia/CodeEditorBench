#!/usr/bin/env python3
"""Display CodeEditorBench results in tabular format across models and ablations."""

import os
import csv
import json
import re
from datetime import datetime
from pathlib import Path
from collections import defaultdict

BENCHMARK_DIR = Path(__file__).parent / "benchmark_runs"

# Main experiment ablations
ABLATIONS = {
    "baseline":   ["baseline"],
    "clean":      ["lora-clean"],
    "dirty":      ["lora-dirty"],
    "unclean74k": ["lora-unclean74k"],
}
ABLATION_LABELS = ["Baseline", "LLM-Cleaning", "Static-Cleaning", "Unfiltered"]

METRICS = ["code_debug", "code_translation", "code_requirement_switch", "code_polishment"]
METRIC_SHORT = {"code_debug": "Debug", "code_translation": "Translate", "code_requirement_switch": "Switch", "code_polishment": "Polish"}

OUTPUT_DIR = Path(__file__).parent / "results_csv"


def infer_model_type(model_name):
    if "instruct" in model_name.lower():
        return "instruct"
    return "base"


def parse_run_name(dirname, ablation_map):
    """Extract (model, ablation_key) from a run directory name using the given ablation map."""
    for ablation_key, patterns in ablation_map.items():
        for pattern in patterns:
            marker = f"-{pattern}-"
            idx = dirname.find(marker)
            if idx != -1:
                model = dirname[:idx]
                return model, ablation_key
    return None, None


def load_metrics_from_csv(csv_path):
    with open(csv_path) as f:
        reader = csv.DictReader(f)
        for row in reader:
            return {k: float(row[k]) for k in METRICS if k in row and row[k]}
    return None


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
TOTAL_EXPECTED = sum(EXPECTED_LINES.values())  # 7960


def compute_generation_pct(run_dir):
    total = 0
    found_any = False
    for ds in CLEAN_DATASETS:
        clean_dir = run_dir / "clean" / ds
        if not clean_dir.exists():
            continue
        for f in clean_dir.glob("*.jsonl"):
            found_any = True
            total += sum(1 for _ in open(f))
    if not found_any:
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

    ps_dir = run_dir / "judge" / "solution_folder" / "processed_solution"
    if not ps_dir.exists():
        return None
    files = list(ps_dir.glob("*.jsonl"))
    if not files:
        return None
    nlines = sum(sum(1 for _ in open(f)) for f in files)
    actual = max(0, nlines - len(files))
    if actual == 0:
        return 0.0
    return actual / TOTAL_EXPECTED * 100


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


def gather_results(ablation_map, model_filter=None):
    """Scan all benchmark runs and collect results for a specific ablation map.

    Returns: {model: {ablation: {metric: value, ..., "status": str,
              "generation_pct": float|None, "eval_pct": float|None}}}
    """
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
        summary_data = load_summary(summary_path) if summary_path.exists() else {}
        status = classify_status(summary_data.get("status", "unknown"), summary_data)

        record = {
            "status": status,
            "_has_metrics": False,
            "run_name": entry.name,
            "run_timestamp": parse_run_timestamp(entry.name),
        }
        record["generation_pct"] = compute_generation_pct(entry)
        record["eval_pct"] = compute_eval_pct(entry)

        csv_primary = entry / "judge" / "metrics" / "metrics_primary.csv"
        csv_plus = entry / "judge" / "metrics" / "metrics_plus.csv"

        if csv_primary.exists() and status in ("eval_complete", "eval_partial"):
            m = load_metrics_from_csv(csv_primary)
            if m:
                record.update(m)
                record["_has_metrics"] = True
                if csv_plus.exists():
                    mp = load_metrics_from_csv(csv_plus)
                    if mp:
                        record["_plus"] = mp

        results[model][ablation] = choose_record(results[model].get(ablation), record)

    return results


def fmt_pct(val):
    if val is None:
        return "-"
    return f"{val*100:.1f}"


def print_table(results, ablation_map, ablation_labels, title=None):
    ablation_keys = list(ablation_map.keys())
    metric_keys = METRICS
    models = sorted(results.keys())

    if not models:
        return

    if title:
        print()
        print("=" * 100)
        print(f"  {title}")
        print("=" * 100)

    # --- Primary metrics table ---
    print()
    print("Primary (metrics_primary.csv)")
    print("-" * 100)

    header_parts = [f"{'Model':<28}"]
    for label in ablation_labels:
        header_parts.append(f"{'':>2}{label:^35}")
    print("".join(header_parts))

    sub_parts = [" " * 28]
    for _ in ablation_keys:
        sub_parts.append("  " + "  ".join(f"{METRIC_SHORT[m]:>7}" for m in metric_keys) + "  ")
    print("".join(sub_parts))
    print("-" * (28 + len(ablation_keys) * 37))

    for model in models:
        row = f"{model:<28}"
        for abl in ablation_keys:
            rec = results[model].get(abl)
            if rec is None or not rec.get("_has_metrics"):
                if rec and rec.get("status") in ("generation_complete", "eval_failed"):
                    status_tag = rec["status"][:6]
                    row += f"  {'(' + status_tag + ')':^35}"
                else:
                    row += "  " + "  ".join(f"{'—':>7}" for _ in metric_keys) + "  "
            else:
                vals = "  ".join(f"{fmt_pct(rec.get(m)):>7}" for m in metric_keys)
                row += "  " + vals + "  "
        print(row)

    # --- Plus metrics table ---
    has_plus = any(
        results[m].get(a, {}).get("_plus")
        for m in models for a in ablation_keys
    )
    if has_plus:
        print()
        print("Plus (metrics_plus.csv)")
        print("-" * 100)
        print("".join(header_parts))
        print("".join(sub_parts))
        print("-" * (28 + len(ablation_keys) * 37))

        for model in models:
            row = f"{model:<28}"
            for abl in ablation_keys:
                rec = results[model].get(abl)
                plus = rec.get("_plus") if rec else None
                if plus is None:
                    if rec and rec.get("_has_metrics"):
                        row += "  " + "  ".join(f"{'—':>7}" for _ in metric_keys) + "  "
                    elif rec and rec.get("status") in ("generation_complete", "eval_failed"):
                        status_tag = rec["status"][:6]
                        row += f"  {'(' + status_tag + ')':^35}"
                    else:
                        row += "  " + "  ".join(f"{'—':>7}" for _ in metric_keys) + "  "
                else:
                    vals = "  ".join(f"{fmt_pct(plus.get(m)):>7}" for m in metric_keys)
                    row += "  " + vals + "  "
            print(row)

    # --- Status summary ---
    print()
    print("Run Status  (gen% = generation progress, eval% = evaluation progress)")
    print("-" * 130)
    print(f"{'':28s}", "  ".join(f"{l:^22}" for l in ablation_labels))
    print(f"{'Model':<28}", "  ".join(f"{'status':>10} {'gen%':>5} {'eval%':>5}" for _ in ablation_keys))
    print("-" * (28 + len(ablation_keys) * 24))
    for model in models:
        row = f"{model:<28}"
        for abl in ablation_keys:
            rec = results[model].get(abl)
            if rec is None:
                row += f"{'—':>12} {'—':>5} {'—':>5}"
            else:
                st = rec["status"]
                short = {"eval_complete": "eval_done", "generation_complete": "gen_done",
                         "eval_failed": "eval_fail", "pending": "pending"}.get(st, st[:10])
                gen_pct = rec.get("generation_pct")
                eval_pct = rec.get("eval_pct")
                gen_str = f"{gen_pct:.0f}%" if gen_pct is not None else "—"
                eval_str = f"{eval_pct:.0f}%" if eval_pct is not None else "—"
                row += f"{short:>12} {gen_str:>5} {eval_str:>5}"
        print(row)

    # --- Missing summary ---
    print()
    not_gen = []
    gen_not_eval = []
    for model in models:
        for abl, label in zip(ablation_keys, ablation_labels):
            rec = results[model].get(abl)
            if rec is None:
                not_gen.append(f"{model} / {label}")
            elif not rec.get("_has_metrics"):
                gen_pct = rec.get("generation_pct")
                eval_pct = rec.get("eval_pct")
                tag = ""
                if gen_pct is not None and gen_pct < 99.9:
                    tag = f" (gen {gen_pct:.0f}%)"
                elif eval_pct is not None:
                    tag = f" (eval {eval_pct:.0f}%)"
                gen_not_eval.append(f"{model} / {label}{tag}")

    if not_gen:
        print(f"Not run ({len(not_gen)}): {'; '.join(not_gen)}")
    if gen_not_eval:
        print(f"Generated but no metrics ({len(gen_not_eval)}): {'; '.join(gen_not_eval)}")

    total_cells = len(models) * len(ablation_keys)
    done = sum(1 for m in models for a in ablation_keys
               if results[m].get(a, {}).get("_has_metrics"))
    print(f"\nTotal models: {len(models)}  |  Cells: {done}/{total_cells} complete")


def fmt_progress(pct):
    if pct is None:
        return "-"
    rounded = round(pct, 1)
    if rounded >= 100.0:
        return "100%"
    return f"{rounded}%"


def save_csvs(results, ablation_map, ablation_labels, suffix=""):
    """Save results to CSV files (combined, use model_type column to filter)."""
    OUTPUT_DIR.mkdir(exist_ok=True)
    ablation_keys = list(ablation_map.keys())

    for metric_set, metric_label in [("primary", None), ("plus", "_plus")]:
        rows = []
        for model in sorted(results.keys()):
            model_type = infer_model_type(model)
            for abl, abl_label in zip(ablation_keys, ablation_labels):
                rec = results[model].get(abl)
                src = rec if metric_label is None else (rec.get("_plus") if rec else None)
                row = {
                    "model": model,
                    "model_type": model_type,
                    "ablation": abl_label,
                    "status": rec["status"] if rec else "-",
                    "generation_pct": fmt_progress(rec["generation_pct"]) if rec else "-",
                    "eval_pct": fmt_progress(rec["eval_pct"]) if rec else "-",
                }
                if src and (rec and rec.get("_has_metrics")) if metric_label is None else src:
                    for m in METRICS:
                        row[m] = f"{src[m]*100:.1f}" if m in src else "-"
                else:
                    for m in METRICS:
                        row[m] = "-"
                rows.append(row)

        fieldnames = ["model", "model_type", "ablation", "status",
                      "generation_pct", "eval_pct"] + METRICS
        tag = f"_{suffix}" if suffix else ""
        combined_path = OUTPUT_DIR / f"results_{metric_set}{tag}.csv"
        with open(combined_path, "w", newline="") as f:
            w = csv.DictWriter(f, fieldnames=fieldnames)
            w.writeheader()
            w.writerows(rows)
        print(f"Saved: {combined_path}")


if __name__ == "__main__":
    # Main experiment
    main_results = gather_results(ABLATIONS)
    print_table(main_results, ABLATIONS, ABLATION_LABELS,
                title="MAIN RESULTS (Full Training Data)")
    print()
    save_csvs(main_results, ABLATIONS, ABLATION_LABELS)

