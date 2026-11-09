"""Evaluation metrics. All are computed against the known competitive equilibrium (CE).

Per run:
- efficiency          realized surplus / max possible surplus (allocative efficiency; 1.0 = perfect)
- price_rmsd          RMS deviation of trade prices from the CE midpoint
- smith_alpha_last    Smith's alpha (100 * rmsd / P*) in the final period (convergence measure)
- price_in_band       fraction of trades priced inside the CE price interval
- quantity_ratio      units traded / CE quantity
- extramarginal       trades involving a unit that should not trade in CE (value < P_low or cost > P_high)
- clip_rate           fraction of submitted orders that violated the budget constraint (agent "irrationality")
- pass_rate, error_rate (LLM failures)
- llm_calls, llm_cost_usd, tokens

Aggregate: `python -m analysis.metrics results/` prints a mean ± 95% CI table and writes results/summary.csv.
"""
from __future__ import annotations

import csv
import json
import math
import sys
from collections import defaultdict
from pathlib import Path

import numpy as np

from market.config import MarketConfig
from market.equilibrium import compute_equilibrium


def compute_run_metrics(cfg: MarketConfig, n_periods: int, trades: list[dict], orders: list[dict],
                        usage: dict) -> dict:
    eqs = [compute_equilibrium(cfg.for_period(p)) for p in range(n_periods)]
    max_surplus = sum(e.max_surplus for e in eqs)
    realized = sum(t["surplus"] for t in trades)
    devs, in_band, extramarginal, per_period = [], 0, 0, []
    for p, e in enumerate(eqs):
        pt = [t for t in trades if t["period"] == p]
        pdevs = [t["price"] - e.price_mid for t in pt]
        devs += pdevs
        in_band += sum(e.price_low <= t["price"] <= e.price_high for t in pt)
        extramarginal += sum(t["buyer_value"] < e.price_low or t["seller_cost"] > e.price_high for t in pt)
        p_eff = sum(t["surplus"] for t in pt) / e.max_surplus if e.max_surplus else float("nan")
        p_rmsd = _rms(pdevs)
        per_period.append({"period": p, "efficiency": p_eff, "price_rmsd": p_rmsd, "n_trades": len(pt),
                           "eq_quantity": e.quantity, "eq_price": e.price_mid,
                           "smith_alpha": 100 * p_rmsd / e.price_mid if e.price_mid and pt else float("nan")})
    submitted = [o for o in orders if o["action"] != "pass" and o.get("raw_price") is not None]
    return {
        "efficiency": realized / max_surplus if max_surplus else float("nan"),
        "price_rmsd": _rms(devs),
        "smith_alpha_last": per_period[-1]["smith_alpha"] if per_period else float("nan"),
        "price_in_band": in_band / len(trades) if trades else float("nan"),
        "quantity_ratio": len(trades) / sum(e.quantity for e in eqs) if eqs else float("nan"),
        "extramarginal": extramarginal,
        "n_trades": len(trades),
        "clip_rate": (sum(o["clipped"] for o in submitted) / len(submitted)) if submitted else 0.0,
        "pass_rate": (sum(o["action"] == "pass" for o in orders) / len(orders)) if orders else 0.0,
        "error_rate": (sum(bool(o.get("error")) for o in orders) / len(orders)) if orders else 0.0,
        "invalid_belief_rate": (sum("invalid_belief" in o for o in orders) / len(orders)) if orders else 0.0,
        "llm_calls": usage.get("calls", 0),
        "llm_cost_usd": usage.get("cost_usd", 0.0),
        "input_tokens": usage.get("input_tokens", 0),
        "output_tokens": usage.get("output_tokens", 0),
        "per_period": per_period,
    }


def _rms(xs) -> float:
    return math.sqrt(sum(x * x for x in xs) / len(xs)) if xs else float("nan")


# ---------------------------------------------------------------------------
SUMMARY_KEYS = ["efficiency", "price_rmsd", "smith_alpha_last", "price_in_band", "quantity_ratio",
                "extramarginal", "clip_rate", "error_rate", "invalid_belief_rate", "llm_calls", "llm_cost_usd"]


def load_all(results_dir: str | Path) -> dict[str, list[dict]]:
    runs = defaultdict(list)
    for f in sorted(Path(results_dir).glob("*/seed_*/metrics.json")):
        m = json.loads(f.read_text())
        runs[m["experiment"]].append(m)
    return dict(runs)


def summarize(results_dir: str | Path) -> list[dict]:
    rows = []
    for name, runs in load_all(results_dir).items():
        row = {"experiment": name, "n_seeds": len(runs)}
        for k in SUMMARY_KEYS:
            vals = np.array([r[k] for r in runs if r.get(k) is not None and not _isnan(r[k])], dtype=float)
            row[k] = float(vals.mean()) if len(vals) else float("nan")
            row[k + "_ci95"] = float(1.96 * vals.std(ddof=1) / math.sqrt(len(vals))) if len(vals) > 1 else 0.0
        rows.append(row)
    return rows


def _isnan(x) -> bool:
    return isinstance(x, float) and math.isnan(x)


def main():
    results_dir = Path(sys.argv[1] if len(sys.argv) > 1 else "results")
    rows = summarize(results_dir)
    if not rows:
        print(f"no runs found under {results_dir}")
        return
    with open(results_dir / "summary.csv", "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        w.writeheader(); w.writerows(rows)
    print(f"{'experiment':<28}{'n':>3}  {'efficiency':>16}  {'price RMSD':>14}  {'alpha(last)':>11}  {'$ cost':>8}")
    for r in sorted(rows, key=lambda r: r["experiment"]):
        print(f"{r['experiment']:<28}{r['n_seeds']:>3}  {r['efficiency']:>8.3f} ± {r['efficiency_ci95']:<5.3f}"
              f"  {r['price_rmsd']:>7.2f} ± {r['price_rmsd_ci95']:<4.1f}  {r['smith_alpha_last']:>11.2f}"
              f"  {r['llm_cost_usd']:>8.3f}")
    print(f"\nwrote {results_dir / 'summary.csv'}")


if __name__ == "__main__":
    main()
