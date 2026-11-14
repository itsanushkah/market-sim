"""Report figures, regenerated from results/ (never edit figures by hand).

    python -m analysis.plots --results results --out report/figures

Produces:
  supply_demand_<market>.png        step supply/demand curves with the CE price
  price_paths_<experiment>.png      trade prices over time vs the CE band (one seed)
  efficiency_by_condition.png       mean efficiency ± 95% CI for every experiment
  rmsd_by_condition.png             mean price RMSD ± 95% CI
  cost_vs_efficiency.png            LLM $ cost vs efficiency (efficiency of collaboration)
  efficiency_by_period.png          mean efficiency per period for each condition (learning across periods)
  surplus_split.png                 buyers' share of surplus vs the competitive-equilibrium share
  prompt_fix_before_after.png       v0 vs v1 prompts: price paths and per-period efficiency
Mock-backend runs are skipped.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

from analysis.metrics import load_all, summarize
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


def plot_efficiency_by_period(results_dir: Path, out: Path, suffix: str = "_r6") -> None:
    """Only runs with the same session length (name ends with `suffix`) are comparable on one chart."""
    runs = {k: v for k, v in load_all(results_dir).items()
            if k.endswith(suffix) and "oracle" not in k and "shock" not in k and "pilot" not in k}
    if not runs:
        return
    fig, ax = plt.subplots(figsize=(5.5, 3.4))
    palette = iter(["#2a6fdb", "#e07b39", "#3a9a5b", "#9b59b6", "#c0392b", "#16a085"])
    for name, rs in sorted(runs.items(), key=lambda kv: kv[0].startswith("baseline")):
        n = min(len(r["per_period"]) for r in rs)
        ys = [sum(r["per_period"][p]["efficiency"] for r in rs) / len(rs) for p in range(n)]
        baseline = name.startswith("baseline")
        ax.plot(range(1, n + 1), ys, marker="o", ms=3, ls="--" if baseline else "-",
                color=C_BASE if baseline else next(palette), label=f"{name.removesuffix(suffix)} (n={len(rs)})")
    ax.set(xlabel="period", ylabel="allocative efficiency", ylim=(0, 1.05),
           title="Efficiency by period (6 rounds/period, symmetric market)")
    ax.set_xticks([1, 2, 3])
    ax.legend(frameon=False, fontsize=7, loc="lower left")
    fig.tight_layout(); fig.savefig(out); plt.close(fig)


def plot_convergence_by_round(results_dir: Path, out: Path, suffix: str = "_r6", market: str = "symmetric") -> None:
    """Convergence speed: mean |trade price - P*| in each round, pooled over periods and seeds."""
    fig, ax = plt.subplots(figsize=(5.5, 3.4))
    palette = iter(["#2a6fdb", "#e07b39", "#3a9a5b", "#9b59b6", "#c0392b", "#16a085"])
    drawn = 0
    for exp_dir in sorted(results_dir.iterdir(), key=lambda d: (d.name.startswith("baseline"), d.name)):
        if not (exp_dir.is_dir() and exp_dir.name.endswith(suffix)) or "oracle" in exp_dir.name:
            continue
        by_round: dict[int, list[float]] = {}
        n = 0
        for run in sorted(exp_dir.glob("seed_*")):
            mf = run / "metrics.json"
            if not mf.exists() or json.loads(mf.read_text()).get("backend") == "mock":
                continue
            cfg = load_market_json(run / "market.json")
            if cfg.name != market:
                continue
            n += 1
            for line in open(run / "trades.jsonl"):
                t = json.loads(line)
                p_star = compute_equilibrium(cfg.for_period(t["period"])).price_mid
                by_round.setdefault(t["round"], []).append(abs(t["price"] - p_star))
        if not by_round:
            continue
        rounds = sorted(by_round)
        baseline = exp_dir.name.startswith("baseline")
        ax.plot([r + 1 for r in rounds], [sum(by_round[r]) / len(by_round[r]) for r in rounds], marker="o", ms=3,
                ls="--" if baseline else "-", color=C_BASE if baseline and "zi_c" in exp_dir.name else next(palette),
                label=f"{exp_dir.name.removesuffix(suffix)} (n={n})")
        drawn += 1
    if drawn:
        ax.set(xlabel="round within period", ylabel="mean |price - P*|", ylim=(0, None),
               title=f"Price convergence within a period ({market} market)")
        ax.legend(frameon=False, fontsize=7)
        fig.tight_layout(); fig.savefig(out)
    plt.close(fig)


def plot_surplus_split(rows: list[dict], out: Path) -> None:
    rows = sorted((r for r in rows if not r["experiment"].endswith("_test")), key=lambda r: r["experiment"])
    if not rows:
        return
    names = [r["experiment"] for r in rows]
    fig, ax = plt.subplots(figsize=(max(5, 0.55 * len(rows)), 3.4))
    ax.bar(names, [r["buyer_share"] for r in rows], yerr=[r["buyer_share_ci95"] for r in rows],
           color=C_MAIN, capsize=3, label="realized buyer share")
    ax.scatter(names, [r["buyer_share_ce"] for r in rows], marker="_", s=400, color="black", zorder=3,
               label="share at competitive price")
    ax.set_ylabel("buyers' share of surplus")
    ax.tick_params(axis="x", rotation=60)
    plt.setp(ax.get_xticklabels(), ha="right")
    ax.legend(frameon=False, fontsize=7)
    fig.tight_layout(); fig.savefig(out); plt.close(fig)


def plot_before_after(results_dir: Path, before: str, after: str, out: Path, seed: int = 0) -> None:
    runs = {k: results_dir / k / f"seed_{seed}" for k in (before, after)}
    if not all((r / "metrics.json").exists() for r in runs.values()):
        return
    fig, axes = plt.subplots(1, 3, figsize=(10, 3.0), gridspec_kw={"width_ratios": [2, 2, 1.2]})
    for ax, (label, run) in zip(axes[:2], runs.items()):
        cfg = load_market_json(run / "market.json")
        trades = [json.loads(l) for l in open(run / "trades.jsonl")]
        m = json.loads((run / "metrics.json").read_text())
        e = compute_equilibrium(cfg)
        ax.axhline(e.price_mid, color="black", lw=0.8, ls="--")
        x0 = 0
        for p in range(len(m["per_period"])):
            pt = [t["price"] for t in trades if t["period"] == p]
            ax.plot(range(x0, x0 + len(pt)), pt, "o-", ms=2.5, lw=0.9, color=C_MAIN)
            x0 += len(pt)
            ax.axvline(x0 - 0.5, color=C_BASE, lw=0.5, ls=":")
        ax.set(title=f"{label}: efficiency {m['efficiency']:.2f}", xlabel="trade #", ylabel="price")
    ax = axes[2]
    w = 0.38
    for i, (label, run) in enumerate(runs.items()):
        m = json.loads((run / "metrics.json").read_text())
        ys = [p["efficiency"] for p in m["per_period"]]
        ax.bar([x + (i - 0.5) * w for x in range(1, len(ys) + 1)], ys, w,
               color=[C_BASE, C_MAIN][i], label=label.split("_")[-1])
    ax.set(xlabel="period", ylabel="efficiency", ylim=(0, 1.05), title="per period")
    ax.set_xticks([1, 2, 3]); ax.legend(frameon=False, fontsize=7)
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
        if json.loads((run / "metrics.json").read_text()).get("backend") == "mock":
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
        plot_surplus_split(rows, out / "surplus_split.png")
    plot_efficiency_by_period(res, out / "efficiency_by_period.png")
    plot_convergence_by_round(res, out / "convergence_by_round.png")
    plot_before_after(res, "llm_full_qwen3b_v0", "llm_full_qwen3b_v1", out / "prompt_fix_before_after.png")
    print(f"figures written to {out}/")


if __name__ == "__main__":
    main()
