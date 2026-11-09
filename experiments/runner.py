"""Run one experiment config over one or more seeds.

    python -m experiments.runner --config experiments/configs/baselines/zi_c.yaml
    python -m experiments.runner --config experiments/configs/llm_traders.yaml --backend mock --seeds 0 1
    python -m experiments.runner --all experiments/configs --backend mock

Writes results/<experiment>/seed_<k>/{config.yaml, trades.jsonl, orders.jsonl, messages.jsonl,
analyst.json, metrics.json, llm_usage.json}.
"""
from __future__ import annotations

import argparse
import copy
import json
import time
from pathlib import Path

import numpy as np
import yaml

from agents.analyst import Analyst
from agents.centralized import LLMPlanner, OraclePlanner, clear_at_price
from agents.llm_trader import LLMTrader
from agents.personas import assign_personas
from agents.zi_trader import ZITrader
from analysis.metrics import compute_run_metrics
from comms.bus import MessageBus
from llm.client import LLMClient, LLMSettings
from market.auctioneer import Auctioneer
from market.config import generate_market, load_market

ROOT = Path(__file__).resolve().parents[1]


def load_experiment(path: str | Path) -> dict:
    with open(path) as f:
        exp = yaml.safe_load(f)
    exp.setdefault("name", Path(path).stem)
    return exp


def build_market(exp: dict, seed: int):
    cfg = load_market(ROOT / exp["market"])
    if exp.get("vary_market_with_seed") and "seed" in cfg.meta:
        raw = yaml.safe_load(open(ROOT / exp["market"]))
        gen = dict(raw["generator"], seed=raw["generator"].get("seed", 0) + seed)
        cfg = generate_market(**gen, name=cfg.name, shock_period=cfg.shock_period, shock_delta=cfg.shock_delta)
    return cfg


def build_traders(exp: dict, cfg, rng, llm: LLMClient | None):
    tcfg = exp.get("traders", {"type": "zi_c"})
    ttype = tcfg.get("type", "zi_c")
    ids = [t.agent_id for t in cfg.traders]
    personas = assign_personas(ids, tcfg.get("personas", "neutral"), rng)
    # Which traders are LLM-driven? "mixed" makes a fraction of each side LLM, the rest ZI-C.
    llm_ids: set[str] = set()
    if ttype == "llm":
        llm_ids = set(ids)
    elif ttype == "mixed":
        frac = tcfg.get("llm_fraction", 0.5)
        for side in (cfg.buyers, cfg.sellers):
            k = int(round(frac * len(side)))
            llm_ids |= {t.agent_id for t in side[:k]}
    traders = []
    for spec in cfg.traders:
        agent_rng = np.random.default_rng(rng.integers(1 << 31))
        if spec.agent_id in llm_ids:
            traders.append(LLMTrader(spec.agent_id, spec.role, spec.units, agent_rng, llm,
                                     persona=personas[spec.agent_id], memory=tcfg.get("memory", True),
                                     chat=tcfg.get("chat", False), price_min=cfg.price_min, price_max=cfg.price_max))
        else:
            traders.append(ZITrader(spec.agent_id, spec.role, spec.units, agent_rng, cfg.price_min, cfg.price_max,
                                    constrained=(ttype != "zi_u")))
    return traders


def run_one(exp: dict, seed: int, out_root: Path) -> dict:
    rng = np.random.default_rng(seed)
    cfg = build_market(exp, seed)
    session = exp.get("session", {})
    n_periods = session.get("n_periods", 3)
    llm_settings = LLMSettings.from_dict(exp.get("llm"))
    llm_settings.cache_dir = str(ROOT / llm_settings.cache_dir)
    needs_llm = (exp.get("traders", {}).get("type") in ("llm", "mixed")
                 or exp.get("analyst", {}).get("mode") == "llm"
                 or exp.get("centralized", {}).get("planner") == "llm")
    llm = LLMClient(llm_settings) if needs_llm else None
    t0 = time.time()

    if "centralized" in exp:
        planner = LLMPlanner(llm) if exp["centralized"]["planner"] == "llm" else OraclePlanner()
        trades, analyst_hist = [], []
        for period in range(n_periods):
            pcfg = cfg.for_period(period)
            price, why = planner.choose_price(pcfg)
            for i, (b, s, p, v, c) in enumerate(clear_at_price(pcfg, price)):
                trades.append({"buyer_id": b, "seller_id": s, "price": p, "period": period, "round": 0,
                               "seq": len(trades), "buyer_value": v, "seller_cost": c, "surplus": v - c})
            analyst_hist.append({"period": period, "planner_price": price, "reasoning": why})
        log = {"trades": trades, "orders": [], "messages": [], "analyst": analyst_hist}
    else:
        channels = set(exp.get("channels", ["analyst", "beliefs"]))
        if exp.get("traders", {}).get("chat"):
            channels.add("chat")
        bus = MessageBus(channels)
        acfg = exp.get("analyst", {"enabled": False})
        analyst = Analyst(bus, acfg.get("mode", "rule"), llm) if acfg.get("enabled", False) else None
        traders = build_traders(exp, cfg, rng, llm)
        auction = Auctioneer(cfg, traders, bus, rng, analyst, n_periods=n_periods,
                             rounds_per_period=session.get("rounds_per_period", 10),
                             enforce_budget=session.get("enforce_budget", True),
                             clear_after_trade=session.get("clear_after_trade", True),
                             max_workers=session.get("max_workers", 8))
        log = auction.run()

    usage = llm.usage.to_dict() if llm else {"calls": 0, "cost_usd": 0.0}
    metrics = compute_run_metrics(cfg, n_periods, log["trades"], log["orders"], usage)
    metrics.update(experiment=exp["name"], seed=seed, wall_time_s=round(time.time() - t0, 2),
                   backend=llm_settings.backend if llm else "none")

    out = out_root / exp["name"] / f"seed_{seed}"
    out.mkdir(parents=True, exist_ok=True)
    yaml.safe_dump(dict(exp, seed=seed), open(out / "config.yaml", "w"), sort_keys=False)
    _jsonl(out / "trades.jsonl", log["trades"])
    _jsonl(out / "orders.jsonl", log["orders"])
    _jsonl(out / "messages.jsonl", log["messages"])
    json.dump(log["analyst"], open(out / "analyst.json", "w"), indent=1)
    json.dump(usage, open(out / "llm_usage.json", "w"), indent=1)
    json.dump(metrics, open(out / "metrics.json", "w"), indent=1)
    market_dump = {"name": cfg.name, "price_min": cfg.price_min, "price_max": cfg.price_max,
                   "shock_period": cfg.shock_period, "shock_delta": cfg.shock_delta,
                   "traders": [{"id": t.agent_id, "role": t.role, "units": t.units} for t in cfg.traders]}
    json.dump(market_dump, open(out / "market.json", "w"), indent=1)
    return metrics


def _jsonl(path: Path, rows: list[dict]) -> None:
    with open(path, "w") as f:
        for r in rows:
            f.write(json.dumps(r, default=float) + "\n")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", help="experiment YAML")
    ap.add_argument("--all", help="run every *.yaml under this directory")
    ap.add_argument("--seeds", type=int, nargs="*", help="override seeds in config")
    ap.add_argument("--backend", choices=["mock", "anthropic", "ollama"], help="override llm.backend")
    ap.add_argument("--model", help="override llm.model")
    ap.add_argument("--periods", type=int, help="override session.n_periods (short test runs)")
    ap.add_argument("--rounds", type=int, help="override session.rounds_per_period")
    ap.add_argument("--name-suffix", default="", help="append to experiment name, e.g. _qwen3b_v1")
    ap.add_argument("--workers", type=int, help="parallel LLM calls per round (use 1 for Ollama on a laptop)")
    ap.add_argument("--out", default=str(ROOT / "results"))
    args = ap.parse_args()

    paths = sorted(Path(args.all).rglob("*.yaml")) if args.all else [Path(args.config)]
    for p in paths:
        exp = load_experiment(p)
        exp = copy.deepcopy(exp)
        if args.backend or args.model:
            exp.setdefault("llm", {})
            if args.backend:
                exp["llm"]["backend"] = args.backend
            if args.model:
                exp["llm"]["model"] = args.model
        if args.periods:
            exp.setdefault("session", {})["n_periods"] = args.periods
        if args.rounds:
            exp.setdefault("session", {})["rounds_per_period"] = args.rounds
        exp["name"] += args.name_suffix
        if args.workers or exp.get("llm", {}).get("backend") == "ollama":
            exp.setdefault("session", {})["max_workers"] = args.workers or 1
        seeds = args.seeds if args.seeds is not None else exp.get("seeds", [0])
        for s in seeds:
            m = run_one(exp, s, Path(args.out))
            print(f"{exp['name']:<28} seed={s}  eff={m['efficiency']:.3f}  "
                  f"rmsd={m['price_rmsd']:.2f}  trades={m['n_trades']}  cost=${m['llm_cost_usd']:.3f}")


if __name__ == "__main__":
    main()
