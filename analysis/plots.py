"""Report figures, regenerated from results/ (never edit figures by hand).

    python -m analysis.plots --results results --out report/figures

Produces:
  supply_demand_<market>.png        step supply/demand curves with the CE price
  price_paths_<experiment>.png      trade prices over time vs the CE band (one seed)
  efficiency_by_condition.png       mean efficiency ± 95% CI for every experiment
  rmsd_by_condition.png             mean price RMSD ± 95% CI
  cost_vs_efficiency.png            LLM $ cost vs efficiency (efficiency of collaboration)
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

from analysis.metrics import summarize
from market.config import MarketConfig, TraderSpec
from market.equilibrium import compute_equilibrium, demand_supply

plt.rcParams.update({"figure.dpi": 150, "axes.spines.top": False, "axes.spines.right": False, "font.size": 9})
C_MAIN, C_BAND, C_BASE = "#2a6fdb", "#e8eef9", "#8a8a8a"


def load_market_json(path: Path) -> MarketConfig:
    m = json.loads(path.read_text())
    traders = [TraderSpec(t["id"], t["role"], t["units"]) for t in m["traders"]]
    return MarketConfig(m["name"], traders, m["price_min"], m["price_max"], m["shock_period"], m["shock_delta"])


def plot_supply_demand(cfg: MarketConfig, out: Path) -> None:
    d, s = demand_supply(cfg)
    e = compute_equilibrium(cfg)
    fig, ax = plt.subplots(figsize=(4.5, 3.2))
    ax.step(range(len(d) + 1), [d[0]] + d, where="pre", label="demand (values)", color=C_MAIN)
    ax.step(range(len(s) + 1), [s[0]] + s, where="pre", label="supply (costs)", color="#d9534f")
    ax.axhspan(e.price_low - 0.5, e.price_high + 0.5, color=C_BAND)
    ax.axvline(e.quantity, ls=":", color=C_BASE)
    ax.set(xlabel="quantity (units)", ylabel="price", title=f"{cfg.name}: Q*={e.quantity}, P*={e.price_mid:g}")
    ax.legend(frameon=False)
    fig.tight_layout(); fig.savefig(out); plt.close(fig)


def plot_price_path(run_dir: Path, out: Path) -> None:
    cfg = load_market_json(run_dir / "market.json")
    trades = [json.loads(l) for l in open(run_dir / "trades.jsonl")]
    meta = json.loads((run_dir / "metrics.json").read_text())
    analyst = json.loads((run_dir / "analyst.json").read_text())
    n_periods = len(meta["per_period"])
    fig, ax = plt.subplots(figsize=(6, 3.2))
    x0 = 0
    for p in range(n_periods):
        e = compute_equilibrium(cfg.for_period(p))
        pt = [t for t in trades if t["period"] == p]
        xs = list(range(x0, x0 + len(pt)))
        ax.fill_between([x0 - 0.5, x0 + max(len(pt), 1) - 0.5], e.price_low - 0.5, e.price_high + 0.5, color=C_BAND)
        ax.plot(xs, [t["price"] for t in pt], "o-", ms=3, color=C_MAIN, lw=1)
        x0 += max(len(pt), 1)
        if p < n_periods - 1:
            ax.axvline(x0 - 0.5, color=C_BASE, lw=0.6, ls=":")
    if analyst and "estimate" in analyst[0]:
        ax.text(0.99, 0.02, f"final analyst estimate: {analyst[-1]['estimate']}", transform=ax.transAxes,
                ha="right", fontsize=7, color=C_BASE)
    ax.set(xlabel="trade # (dotted lines = period boundaries)", ylabel="price",
           title=f"{meta['experiment']} (seed {meta['seed']}): efficiency {meta['efficiency']:.2f}")
    fig.tight_layout(); fig.savefig(out); plt.close(fig)


def plot_bars(rows: list[dict], key: str, ylabel: str, out: Path, ref: float | None = None) -> None:
    rows = sorted(rows, key=lambda r: r["experiment"])
    names = [r["experiment"] for r in rows]
    fig, ax = plt.subplots(figsize=(max(5, 0.55 * len(rows)), 3.4))
    colors = [C_BASE if n.startswith("baseline") else C_MAIN for n in names]
    ax.bar(names, [r[key] for r in rows], yerr=[r[key + "_ci95"] for r in rows], color=colors, capsize=3)
    if ref is not None:
        ax.axhline(ref, color="black", lw=0.6, ls="--")
    ax.set_ylabel(ylabel)
    ax.tick_params(axis="x", rotation=60)
    plt.setp(ax.get_xticklabels(), ha="right")
    fig.tight_layout(); fig.savefig(out); plt.close(fig)


def plot_cost_vs_eff(rows: list[dict], out: Path) -> None:
    rows = [r for r in rows if r["llm_cost_usd"] and r["llm_cost_usd"] > 0]
    if not rows:
        return
    fig, ax = plt.subplots(figsize=(4.5, 3.2))
    for r in rows:
        ax.errorbar(r["llm_cost_usd"], r["efficiency"], yerr=r["efficiency_ci95"], fmt="o", color=C_MAIN)
        ax.annotate(r["experiment"], (r["llm_cost_usd"], r["efficiency"]), fontsize=6, xytext=(3, 3),
                    textcoords="offset points")
    ax.set(xlabel="LLM cost per run (USD)", ylabel="allocative efficiency")
    fig.tight_layout(); fig.savefig(out); plt.close(fig)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--results", default="results")
    ap.add_argument("--out", default="report/figures")
    ap.add_argument("--seed", type=int, default=0, help="which seed to draw price paths for")
    args = ap.parse_args()
    res, out = Path(args.results), Path(args.out)
    out.mkdir(parents=True, exist_ok=True)

    seen_markets = set()
    for exp_dir in sorted(p for p in res.iterdir() if p.is_dir()):
        run = exp_dir / f"seed_{args.seed}"
        if not (run / "metrics.json").exists():
            continue
        cfg = load_market_json(run / "market.json")
        if cfg.name not in seen_markets:
            plot_supply_demand(cfg, out / f"supply_demand_{cfg.name}.png"); seen_markets.add(cfg.name)
        if (run / "trades.jsonl").stat().st_size > 0:
            plot_price_path(run, out / f"price_paths_{exp_dir.name}.png")

    rows = summarize(res)
    if rows:
        plot_bars(rows, "efficiency", "allocative efficiency", out / "efficiency_by_condition.png", ref=1.0)
        plot_bars(rows, "price_rmsd", "price RMSD from P*", out / "rmsd_by_condition.png")
        plot_cost_vs_eff(rows, out / "cost_vs_efficiency.png")
    print(f"figures written to {out}/")


if __name__ == "__main__":
    main()
