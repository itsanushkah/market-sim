"""Recompute metrics.json for saved runs from their logs (use after adding or changing a metric).

    python -m analysis.recompute results
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import yaml

from analysis.metrics import compute_run_metrics
from analysis.plots import load_market_json


def recompute(run: Path) -> None:
    old = json.loads((run / "metrics.json").read_text())
    cfg = load_market_json(run / "market.json")
    n_periods = yaml.safe_load(open(run / "config.yaml")).get("session", {}).get("n_periods", 3)
    trades = [json.loads(l) for l in open(run / "trades.jsonl")]
    orders = [json.loads(l) for l in open(run / "orders.jsonl")]
    usage = json.loads((run / "llm_usage.json").read_text())
    new = compute_run_metrics(cfg, n_periods, trades, orders, usage)
    for k in ("experiment", "seed", "wall_time_s", "backend"):
        new[k] = old.get(k)
    (run / "metrics.json").write_text(json.dumps(new, indent=1))


if __name__ == "__main__":
    root = Path(sys.argv[1] if len(sys.argv) > 1 else "results")
    runs = sorted(p.parent for p in root.glob("*/seed_*/metrics.json"))
    for r in runs:
        recompute(r)
    print(f"recomputed {len(runs)} runs")
