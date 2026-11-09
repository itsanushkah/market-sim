"""Demo dashboard: replays a logged run (no live LLM calls, so the demo cannot fail on the network).

    streamlit run dashboard/app.py
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import matplotlib.pyplot as plt
import streamlit as st

from analysis.metrics import summarize
from analysis.plots import load_market_json
from market.equilibrium import compute_equilibrium

RESULTS = ROOT / "results"
st.set_page_config(page_title="Market Sim Replay", layout="wide")
st.title("Multi-agent market simulation: replay")

exps = sorted(p.name for p in RESULTS.iterdir() if p.is_dir()) if RESULTS.exists() else []
if not exps:
    st.info("No results yet. Run `python -m experiments.runner --all experiments/configs --backend mock` first.")
    st.stop()

tab_replay, tab_compare = st.tabs(["Replay a run", "Compare conditions"])

with tab_replay:
    c1, c2 = st.columns(2)
    exp = c1.selectbox("Experiment", exps)
    seeds = sorted(p.name for p in (RESULTS / exp).iterdir() if p.is_dir())
    seed = c2.selectbox("Seed", seeds)
    run = RESULTS / exp / seed
    cfg = load_market_json(run / "market.json")
    trades = [json.loads(l) for l in open(run / "trades.jsonl")]
    orders = [json.loads(l) for l in open(run / "orders.jsonl")]
    msgs = [json.loads(l) for l in open(run / "messages.jsonl")]
    metrics = json.loads((run / "metrics.json").read_text())

    m1, m2, m3, m4 = st.columns(4)
    m1.metric("Efficiency", f"{metrics['efficiency']:.3f}")
    m2.metric("Price RMSD", f"{metrics['price_rmsd']:.2f}")
    m3.metric("Trades", metrics["n_trades"])
    m4.metric("LLM cost", f"${metrics['llm_cost_usd']:.3f}")

    n_steps = max(1, len(trades))
    step = st.slider("Replay up to trade #", 1, n_steps, n_steps)
    shown = trades[:step]
    fig, ax = plt.subplots(figsize=(8, 3))
    for p in range(len(metrics["per_period"])):
        e = compute_equilibrium(cfg.for_period(p))
        idx = [i for i, t in enumerate(shown) if t["period"] == p]
        if idx:
            ax.fill_between([idx[0] - 0.5, idx[-1] + 0.5], e.price_low - 0.5, e.price_high + 0.5, color="#e8eef9")
    ax.plot([t["price"] for t in shown], "o-", ms=3)
    ax.set_xlabel("trade #"); ax.set_ylabel("price")
    st.pyplot(fig)

    if shown:
        cur = shown[-1]
        rnd_orders = [o for o in orders if o["period"] == cur["period"] and o["round"] == cur["round"]]
        st.subheader(f"Period {cur['period'] + 1}, round {cur['round'] + 1}: agent decisions")
        st.dataframe([{k: o.get(k) for k in ("agent_id", "role", "action", "raw_price", "price", "unit",
                                              "belief", "clipped", "traded", "reasoning")} for o in rnd_orders],
                     use_container_width=True)
        rnd_msgs = [m for m in msgs if m["period"] == cur["period"] and m["round"] <= cur["round"]
                    and m["channel"] in ("analyst", "chat")][-8:]
        if rnd_msgs:
            st.subheader("Messages")
            for m in rnd_msgs:
                st.markdown(f"**[{m['channel']}] {m['sender']}** (r{m['round'] + 1}): {m['content']}")

with tab_compare:
    rows = summarize(RESULTS)
    st.dataframe([{k: (round(v, 3) if isinstance(v, float) else v) for k, v in r.items() if not k.endswith("_ci95")}
                  for r in rows], use_container_width=True)
    fig_dir = ROOT / "report" / "figures"
    for name in ("efficiency_by_condition.png", "rmsd_by_condition.png", "cost_vs_efficiency.png"):
        if (fig_dir / name).exists():
            st.image(str(fig_dir / name))
