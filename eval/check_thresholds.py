#!/usr/bin/env python3
"""
Читает последний прогон из eval/runs/ и проверяет пороги из thresholds.yaml.
Завершается с sys.exit(1) при нарушении — используется как gate перед релизом.

Запуск:
    python eval/check_thresholds.py
"""
import json
import sys
from pathlib import Path

import yaml


def main() -> None:
    runs_dir = Path("eval/runs")
    run_files = sorted(runs_dir.glob("*.json"))
    if not run_files:
        print("ERROR: нет файлов в eval/runs/", file=sys.stderr)
        sys.exit(1)

    last_run = json.loads(run_files[-1].read_text(encoding="utf-8"))
    thresholds = yaml.safe_load(Path("eval/thresholds.yaml").read_text(encoding="utf-8"))

    agg = last_run["aggregates"]
    failures = []

    if agg["correctness_avg"] < thresholds["correctness_avg"]:
        failures.append(
            f"correctness_avg = {agg['correctness_avg']:.2f} "
            f"< порог {thresholds['correctness_avg']}"
        )
    if agg["min_correctness"] < thresholds["min_correctness"]:
        failures.append(
            f"min_correctness = {agg['min_correctness']} "
            f"< порог {thresholds['min_correctness']}"
        )

    if failures:
        print(f"ПОРОГИ НАРУШЕНЫ (прогон: {run_files[-1].name}):")
        for msg in failures:
            print(f"  ✗ {msg}")
        sys.exit(1)

    print(f"Все пороги соблюдены ✓  (прогон: {run_files[-1].name})")
    print(f"  correctness_avg  = {agg['correctness_avg']}")
    print(f"  min_correctness  = {agg['min_correctness']}")


if __name__ == "__main__":
    main()