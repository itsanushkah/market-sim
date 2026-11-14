"""Evaluation metrics. All are computed against the known competitive equilibrium (CE).

Per run:
- efficiency          realized surplus / max possible surplus (allocative efficiency; 1.0 = perfect)
- price_rmsd          RMS deviation of trade prices from the CE midpoint
- smith_alpha_last    Smith's alpha (100 * rmsd / P*) in the final period (convergence measure)
- price_in_band       fraction of trades priced inside the CE price interval
- converge_round      convergence speed: mean over periods of the first round (1-based) from which every
                      later trade in that period is within +/-10% of P*. A period that never settles counts
                      as rounds_per_period + 1.
- settled_share       fraction of trades that happen after the market has settled (same definition)
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
from market.equilibrium import compute_equilibrium, demand_supply


def compute_run_metrics(cfg: MarketConfig, n_periods: int, trades: list[dict], orders: list[dict],
                        usage: dict) -> dict:
    eqs = [compute_equilibrium(cfg.for_period(p)) for p in range(n_periods)]
    max_surplus = sum(e.max_surplus for e in eqs)
    realized = sum(t["surplus"] for t in trades)
    devs, in_band, extramarginal, per_period = [], 0, 0, []
    n_rounds = 1 + max([o["round"] for o in orders] + [t.get("round", 0) for t in trades], default=0)
    settled_trades = 0
    for p, e in enumerate(eqs):
        pt = [t for t in trades if t["period"] == p]
        pdevs = [t["price"] - e.price_mid for t in pt]
        devs += pdevs
        in_band += sum(e.price_low <= t["price"] <= e.price_high for t in pt)
        extramarginal += sum(t["buyer_value"] < e.price_low or t["seller_cost"] > e.price_high for t in pt)
        p_eff = sum(t["surplus"] for t in pt) / e.max_surplus if e.max_surplus else float("nan")
        p_rmsd = _rms(pdevs)
        conv_round, n_settled = _convergence(pt, e.price_mid, n_rounds)
        settled_trades += n_settled
        per_period.append({"period": p, "efficiency": p_eff, "price_rmsd": p_rmsd, "n_trades": len(pt),
                           "eq_quantity": e.quantity, "eq_price": e.price_mid,
                           "converge_round": conv_round, "settled_trades": n_settled,
                           "smith_alpha": 100 * p_rmsd / e.price_mid if e.price_mid and pt else float("nan")})
    # Surplus split: what share of realized surplus went to buyers, vs. the share they'd get at the CE price.
    buyer_surplus = sum(t["buyer_value"] - t["price"] for t in trades)
    ce_buyer = 0.0
    for p, e in enumerate(eqs):
        d, _ = demand_supply(cfg.for_period(p))
        ce_buyer += sum(v - e.price_mid for v in d[:e.quantity])
    submitted = [o for o in orders if o["action"] != "pass" and o.get("raw_price") is not None]
    return {
        "efficiency": realized / max_surplus if max_surplus else float("nan"),
        "price_rmsd": _rms(devs),
        "smith_alpha_last": per_period[-1]["smith_alpha"] if per_period else float("nan"),
        "price_in_band": in_band / len(trades) if trades else float("nan"),
        "converge_round": float(np.mean([pp["converge_round"] for pp in per_period])) if per_period else float("nan"),
        "settled_share": settled_trades / len(trades) if trades else float("nan"),
        "quantity_ratio": len(trades) / sum(e.quantity for e in eqs) if eqs else float("nan"),
        "extramarginal": extramarginal,
        "n_trades": len(trades),
        "buyer_share": buyer_surplus / realized if realized else float("nan"),
        "buyer_share_ce": ce_buyer / max_surplus if max_surplus else float("nan"),
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


CONVERGENCE_TOL = 0.10  # a trade is "near equilibrium" if within 10% of P*


def _convergence(period_trades: list[dict], p_star: float, n_rounds: int) -> tuple[int, int]:
    """(first 1-based round from which all later trades are near P*, number of trades in that settled tail).
    If the last trade of the period is still off, the period never settled: (n_rounds + 1, 0)."""
    tail = 0
    for t in reversed(period_trades):
        if abs(t["price"] - p_star) > CONVERGENCE_TOL * p_star:
            break
        tail += 1
    if tail == 0:
        return n_rounds + 1, 0
    first = period_trades[len(period_trades) - tail]
    # If an off-price trade happened earlier in the same round, the market settled from the next round on.
    earlier_off = len(period_trades) > tail and period_trades[len(period_trades) - tail - 1].get("round", 0) == first.get("round", 0)
    rnd = first.get("round", 0) + 1 + (1 if earlier_off else 0)
    if earlier_off:
        tail = sum(t.get("round", 0) + 1 >= rnd for t in period_trades[len(period_trades) - tail:])
    return (rnd, tail) if tail else (n_rounds + 1, 0)


def _rms(xs) -> float:
    return math.sqrt(sum(x * x for x in xs) / len(xs)) if xs else float("nan")


# ---------------------------------------------------------------------------
SUMMARY_KEYS = ["efficiency", "price_rmsd", "smith_alpha_last", "price_in_band", "converge_round", "settled_share", "quantity_ratio",
                "buyer_share", "buyer_share_ce",
                "extramarginal", "clip_rate", "error_rate", "invalid_belief_rate", "llm_calls", "llm_cost_usd"]


def load_all(results_dir: str | Path, include_mock: bool = False) -> dict[str, list[dict]]:
    """Load every run's metrics. Mock-backend runs are excluded unless asked for: they are not findings."""
    runs = defaultdict(list)
    for f in sorted(Path(results_dir).glob("*/seed_*/metrics.json")):
        m = json.loads(f.read_text())
        if m.get("backend") == "mock" and not include_mock:
            continue
        runs[m["experiment"]].append(m)
    return dict(runs)


def summarize(results_dir: str | Path, include_mock: bool = False) -> list[dict]:
    rows = []
    for name, runs in load_all(results_dir, include_mock).items():
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
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    results_dir = Path(args[0] if args else "results")
    rows = summarize(results_dir, include_mock="--include-mock" in sys.argv)
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
