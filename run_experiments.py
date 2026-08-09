#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

os.environ.setdefault("MPLCONFIGDIR", "/tmp/hybrid-attendance-matplotlib")

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "src"))

from hybrid_attendance.config import load_config
from hybrid_attendance.simulator import ExperimentResult, ExperimentSimulator
from hybrid_attendance.zkp import Groth16ZKP, IdealZKP


SCENARIO_LABELS = {
    "proposed": "Proposed (60/40 + ZKP)",
    "random": "Random + ZKP",
    "no_zkp": "Proposed without ZKP",
}


def write_results(result: ExperimentResult, output_root: Path) -> None:
    scenario_dir = output_root / result.scenario
    scenario_dir.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(result.session_metrics).to_csv(scenario_dir / "session_metrics.csv", index=False)
    zkp_columns = [
        "scenario", "session_id", "student_id", "proof_generation_ms", "verification_ms", "valid"
    ]
    pd.DataFrame(result.zkp_logs, columns=zkp_columns).to_csv(
        scenario_dir / "zkp_logs.csv", index=False
    )


def run_evm_measurement(results: list[ExperimentResult], output_root: Path) -> dict[str, Any]:
    plan = {result.scenario: result.evm_plan for result in results}
    plan_path = output_root / "evm_plan.json"
    result_path = output_root / "evm_gas_results.json"
    plan_path.write_text(json.dumps(plan, indent=2), encoding="utf-8")
    subprocess.run(
        ["node", str(ROOT / "scripts/evm_gas.mjs"), str(plan_path), str(result_path)],
        cwd=ROOT,
        check=True,
    )
    return json.loads(result_path.read_text(encoding="utf-8"))


def merge_gas(
    results: list[ExperimentResult], gas_results: dict[str, Any], output_root: Path
) -> None:
    for result in results:
        gas_by_session = {int(row["session_id"]): row for row in gas_results[result.scenario]}
        for metric in result.session_metrics:
            gas = gas_by_session[int(metric["session_id"])]
            for field in ("start_gas", "submit_gas", "close_gas", "total_gas"):
                metric[field] = int(gas[field])
        scenario_dir = output_root / result.scenario
        pd.DataFrame(result.session_metrics).to_csv(scenario_dir / "session_metrics.csv", index=False)
        gas_columns = ["scenario", "session_id", "start_gas", "submit_gas", "close_gas", "total_gas"]
        gas_rows = [
            {column: metric[column] for column in gas_columns}
            for metric in result.session_metrics
        ]
        pd.DataFrame(gas_rows, columns=gas_columns).to_csv(
            scenario_dir / "gas_logs.csv", index=False
        )


def build_summary(results: list[ExperimentResult], output_root: Path) -> pd.DataFrame:
    rows = []
    for result in results:
        frame = pd.DataFrame(result.session_metrics)
        rows.append(
            {
                "scenario": result.scenario,
                "mean_selection_precision": frame["selection_precision"].mean(),
                "mean_prediction_error": frame["mean_prediction_error"].mean(),
                "final_fl_accuracy": frame.iloc[-1]["fl_accuracy"],
                "mean_fl_accuracy": frame["fl_accuracy"].mean(),
                "mean_total_gas": frame["total_gas"].mean(),
                "total_gas": frame["total_gas"].sum(),
                "mean_wall_clock_seconds": frame["wall_clock_seconds"].mean(),
                "total_wall_clock_seconds": frame["wall_clock_seconds"].sum(),
                "zkp_success_rate": (
                    frame["zkp_valid"].sum() / frame["zkp_received"].sum()
                    if frame["zkp_received"].sum()
                    else float("nan")
                ),
                "mean_zkp_generation_ms": frame["avg_zkp_generation_ms"].mean(),
                "mean_zkp_verification_ms": frame["avg_zkp_verification_ms"].mean(),
            }
        )
    summary = pd.DataFrame(rows)
    summary.to_csv(output_root / "comparison_summary.csv", index=False)
    (output_root / "comparison_summary.json").write_text(
        summary.to_json(orient="records", indent=2), encoding="utf-8"
    )
    return summary


def make_plots(results: list[ExperimentResult], summary: pd.DataFrame, output_root: Path) -> None:
    plot_dir = output_root / "plots"
    plot_dir.mkdir(parents=True, exist_ok=True)
    colors = {"proposed": "#1f77b4", "random": "#ff7f0e", "no_zkp": "#d62728"}
    fig, axes = plt.subplots(2, 2, figsize=(12, 8), constrained_layout=True)
    metrics = [
        ("selection_precision", "Selection precision"),
        ("mean_prediction_error", "Mean prediction error"),
        ("fl_accuracy", "Federated model accuracy"),
        ("total_gas", "Gas per session"),
    ]
    for axis, (field, title) in zip(axes.flat, metrics):
        for result in results:
            frame = pd.DataFrame(result.session_metrics)
            axis.plot(
                frame["session_id"], frame[field], label=SCENARIO_LABELS[result.scenario],
                color=colors[result.scenario], linewidth=1.8
            )
        axis.set_title(title)
        axis.set_xlabel("Session")
        axis.grid(alpha=0.25)
    axes[0, 0].legend(fontsize=8)
    fig.savefig(plot_dir / "session_metrics.png", dpi=180)
    plt.close(fig)

    fig, axes = plt.subplots(1, 3, figsize=(13, 4), constrained_layout=True)
    labels = [SCENARIO_LABELS[value] for value in summary["scenario"]]
    palette = [colors[value] for value in summary["scenario"]]
    axes[0].bar(labels, summary["mean_selection_precision"], color=palette)
    axes[0].set_title("Mean selection precision")
    axes[0].set_ylim(0, 1)
    axes[1].bar(labels, summary["final_fl_accuracy"], color=palette)
    axes[1].set_title("Final FL accuracy")
    axes[1].set_ylim(0, 1)
    axes[2].bar(labels, summary["zkp_success_rate"].fillna(0), color=palette)
    axes[2].set_title("ZKP verification success")
    axes[2].set_ylim(0, 1)
    for axis in axes:
        axis.tick_params(axis="x", rotation=20, labelsize=8)
        axis.grid(axis="y", alpha=0.25)
    fig.savefig(plot_dir / "scenario_comparison.png", dpi=180)
    plt.close(fig)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run all hybrid attendance experiments")
    parser.add_argument("--config", default="config.yaml")
    parser.add_argument(
        "--scenarios", nargs="+", default=["proposed", "random", "no_zkp"],
        choices=["proposed", "random", "no_zkp"]
    )
    parser.add_argument("--zkp-backend", choices=["groth16", "ideal"], help="override config")
    parser.add_argument("--skip-evm", action="store_true", help="leave gas fields at zero")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    config = load_config(ROOT / args.config)
    backend_name = args.zkp_backend or config.zkp.backend
    zkp = Groth16ZKP(ROOT) if backend_name == "groth16" else IdealZKP()
    output_root = ROOT / config.storage.output_dir
    output_root.mkdir(parents=True, exist_ok=True)
    results: list[ExperimentResult] = []
    try:
        for scenario in args.scenarios:
            print(f"Running scenario: {scenario}", flush=True)
            result = ExperimentSimulator(config, scenario, zkp, ROOT).run()
            write_results(result, output_root)
            results.append(result)
    finally:
        zkp.close()

    if not args.skip_evm:
        gas_results = run_evm_measurement(results, output_root)
        merge_gas(results, gas_results, output_root)
    else:
        merge_gas(
            results,
            {
                result.scenario: [
                    {"session_id": row["session_id"], "start_gas": 0, "submit_gas": 0,
                     "close_gas": 0, "total_gas": 0}
                    for row in result.session_metrics
                ]
                for result in results
            },
            output_root,
        )
    summary = build_summary(results, output_root)
    make_plots(results, summary, output_root)
    print(summary.to_string(index=False), flush=True)


if __name__ == "__main__":
    main()

