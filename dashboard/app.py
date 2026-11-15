"""Demo dashboard.

    streamlit run dashboard/app.py

Tabs: a plain-language explanation, a live run (calls the local model through Ollama), a replay of saved
runs (never calls a model, so it cannot fail during a demo) and a comparison of the experimental setups.
"""
from __future__ import annotations

import json
import os
import sys
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import matplotlib.pyplot as plt
import streamlit as st
import yaml

from analysis.metrics import summarize
from analysis.plots import load_market_json
from experiments.runner import run_one
from market.config import load_market
from market.equilibrium import compute_equilibrium, demand_supply

RESULTS = ROOT / "results"
FIGS = ROOT / "report" / "figures"
MODEL = "qwen2.5:3b"
# Tests set MARKET_SIM_LIVE_BACKEND=mock to exercise the live tab without a model. The demo always uses Ollama.
LIVE_BACKEND = os.environ.get("MARKET_SIM_LIVE_BACKEND", "ollama")

# Plain-language names for the saved experiments. Anything not listed keeps its raw name.
FRIENDLY = {
    "llm_full_qwen3b_r6": "AI traders + analyst (full system)",
    "abl_no_analyst_qwen3b_r6": "AI traders, no analyst",
    "abl_no_comms_qwen3b_r6": "AI traders, no communication at all",
    "rob_shock_llm_qwen3b_r6": "AI traders + analyst, costs jump mid-session",
    "baseline_zi_c_r6": "Random traders (baseline)",
    "baseline_zi_u_r6": "Random traders allowed to lose money",
    "rob_shock_zi_c_r6": "Random traders, costs jump mid-session",
    "baseline_oracle_r6": "Perfect planner (upper limit)",
    "baseline_centralized_llm_qwen3b": "One AI that sees everyone's secrets",
    "llm_full_qwen3b_v1": "AI traders + analyst, longer session (10 rounds)",
    "llm_full_qwen3b_v0": "First version, before the prompt fixes (10 rounds)",
    "pilot_llm_full_qwen3b_r6": "Small market: AI traders + analyst",
    "pilot_no_analyst_qwen3b_r6": "Small market: AI traders, no analyst",
    "pilot_zi_c_r6": "Small market: random traders",
}
SCOREBOARD = ["baseline_zi_c_r6", "abl_no_comms_qwen3b_r6", "abl_no_analyst_qwen3b_r6",
              "baseline_centralized_llm_qwen3b", "llm_full_qwen3b_r6", "baseline_oracle_r6"]
ORDER_COLUMNS = {"agent_id": "Trader", "role": "Role", "unit": "Secret value / cost", "action": "Action",
                 "raw_price": "Price it chose", "price": "Price after safety rule", "belief": "Its guess of the fair price",
                 "traded": "Traded?", "reasoning": "Why (the AI's own words)"}


def friendly(name: str) -> str:
    return FRIENDLY.get(name, name)


def real_seeds(exp_dir: Path) -> list[str]:
    """Seeds of an experiment that were not produced by the mock backend (mock runs are not results)."""
    out = []
    for p in sorted(exp_dir.iterdir()):
        f = p / "metrics.json"
        if p.is_dir() and f.exists() and json.loads(f.read_text()).get("backend") != "mock":
            out.append(p.name)
    return out


def price_chart(cfg, trades: list[dict], n_periods: int):
    """Trade prices in order, with the fair-price band for each period shaded."""
    fig, ax = plt.subplots(figsize=(8, 3))
    for p in range(n_periods):
        e = compute_equilibrium(cfg.for_period(p))
        idx = [i for i, t in enumerate(trades) if t["period"] == p]
        if idx:
            ax.fill_between([idx[0] - 0.5, idx[-1] + 0.5], e.price_low - 2, e.price_high + 2, color="#cfe0ff",
                            label="fair price" if p == 0 else None)
            if p:
                ax.axvline(idx[0] - 0.5, color="#bbbbbb", lw=0.8, ls=":")
            ax.text(idx[0] - 0.4, cfg.price_max * 0.97, f"period {p + 1}", fontsize=7, va="top", color="#666666")
    ax.plot([t["price"] for t in trades], "o-", ms=3, color="#2a6fdb", label="trade price")
    ax.set_xlabel("trade number"); ax.set_ylabel("price"); ax.set_ylim(cfg.price_min, cfg.price_max)
    if trades:
        ax.legend(frameon=False, fontsize=7, loc="lower right")
    fig.tight_layout()
    return fig


def outcome(o: dict) -> str:
    if o.get("error"):
        return "AI gave an unusable answer"
    if o["action"] == "pass" or o.get("raw_price") is None:
        return "Sat this round out"
    if o.get("traded"):
        return "✅ Traded" + (" (safety rule adjusted the price)" if o.get("clipped") else "")
    if o.get("clipped"):
        return "⚠️ Would have lost money; safety rule adjusted the price"
    return "Offer left waiting"


def order_rows(orders: list[dict]) -> list[dict]:
    rows = []
    for o in orders:
        row = {label: o.get(k) for k, label in ORDER_COLUMNS.items() if k != "traded"}
        row = {"Trader": row.pop("Trader"), "Result": outcome(o), **row}
        rows.append(row)
    return rows


def trade_story(trades: list[dict]) -> list[str]:
    """One plain sentence per trade: who bought from whom, and what each side gained."""
    out = []
    for t in trades:
        b_gain, s_gain = t["buyer_value"] - t["price"], t["price"] - t["seller_cost"]
        note = "" if t["surplus"] > 0 else " This trade created no benefit."
        out.append(f"**{t['buyer_id']}** bought from **{t['seller_id']}** at **{t['price']:g}**. "
                   f"The buyer valued it at {t['buyer_value']:g}, so gained {b_gain:g}; "
                   f"it cost the seller {t['seller_cost']:g}, so gained {s_gain:g}.{note}")
    return out


def supply_demand_chart(cfg):
    """The 'staircase' picture: buyers' values from high to low, sellers' costs from low to high."""
    d, s_ = demand_supply(cfg)
    e = compute_equilibrium(cfg)
    fig, ax = plt.subplots(figsize=(5, 3))
    ax.step(range(len(d) + 1), [d[0]] + d, where="pre", color="#2a6fdb", label="what buyers would pay")
    ax.step(range(len(s_) + 1), [s_[0]] + s_, where="pre", color="#d9534f", label="what sellers need")
    ax.axhspan(e.price_low - 2, e.price_high + 2, color="#cfe0ff", label="fair price")
    ax.axvline(e.quantity, ls=":", color="#888888")
    ax.set_xlabel("units traded"); ax.set_ylabel("price")
    ax.legend(frameon=False, fontsize=7)
    fig.tight_layout()
    return fig


def headline_chart(by_name: dict):
    names = [n for n in SCOREBOARD if n in by_name]
    fig, ax = plt.subplots(figsize=(8, 0.45 * len(names) + 0.9))
    vals = [by_name[n]["efficiency"] for n in names]
    colors = ["#2a6fdb" if n == "llm_full_qwen3b_r6" else "#9aa5b1" for n in names]
    ax.barh([friendly(n) for n in names], vals, xerr=[by_name[n]["efficiency_ci95"] for n in names],
            color=colors, error_kw={"lw": 1, "capsize": 2})
    for i, v in enumerate(vals):
        ax.text(0.02, i, f"{v:.0%}", va="center", color="white", fontsize=9, fontweight="bold")
    ax.set_xlim(0, 1.05); ax.set_xlabel("share of the possible gains from trade that was captured")
    ax.spines[["top", "right"]].set_visible(False)
    fig.tight_layout()
    return fig


def verdict(m: dict, base: dict | None) -> str:
    eff = m["efficiency"]
    text = f"This run captured **{eff:.0%}** of the possible gains from trade."
    if base:
        diff = eff - base["efficiency"]
        how = "better than" if diff > 0.02 else "worse than" if diff < -0.02 else "about the same as"
        text += f" That is {how} random traders on the same market, who average {base['efficiency']:.0%}."
    if m.get("n_trades") and m.get("buyer_share") is not None:
        gap = m["buyer_share"] - m["buyer_share_ce"]
        if abs(gap) > 0.08:
            text += (f" Prices ran {'low' if gap > 0 else 'high'}: buyers took {m['buyer_share']:.0%} of the gains, "
                     f"against {m['buyer_share_ce']:.0%} at the fair price.")
        else:
            text += " Buyers and sellers split the gains about as they would at the fair price."
    return text


def random_baseline(by_name: dict, market: str, rounds: int) -> dict | None:
    key = {("pilot", 6): "pilot_zi_c_r6", ("symmetric", 6): "baseline_zi_c_r6", ("symmetric", 10): "baseline_zi_c",
           ("shock", 6): "rob_shock_zi_c_r6", ("shock", 10): "rob_shock_zi_c"}.get((market, rounds))
    return by_name.get(key) if key else None


def secrets_table(cfg) -> list[dict]:
    return [{"Trader": t.agent_id, "Role": t.role,
             ("Most it would pay / least it would accept, per unit"): ", ".join(str(u) for u in t.units)}
            for t in cfg.traders]


def ollama_ready() -> bool:
    try:
        with urllib.request.urlopen("http://localhost:11434/api/tags", timeout=2) as r:
            return any(m["name"] == MODEL for m in json.loads(r.read()).get("models", []))
    except Exception:
        return False


st.set_page_config(page_title="AI market simulation", layout="wide")
st.title("Can AI traders find the right price?")
st.caption("A multi-agent market simulation · CMPSC 448 final project")

runs_by_exp = {p.name: real_seeds(p) for p in sorted(RESULTS.iterdir()) if p.is_dir()} if RESULTS.exists() else {}
runs_by_exp = {k: v for k, v in runs_by_exp.items() if v}
rows = summarize(RESULTS) if runs_by_exp else []
by_name = {r["experiment"]: r for r in rows}

tab_about, tab_live, tab_replay, tab_compare = st.tabs(
    ["1 · What is this?", "2 · Run it live", "3 · Replay a saved run", "4 · Compare setups"])

# ---------------------------------------------------------------------------------------------------------
with tab_about:
    left, right = st.columns([3, 2])
    with left:
        st.markdown("""
#### The idea in one minute

Imagine a small market for one product. There are **buyers** and **sellers**, and each one is a separate AI agent.

- Every buyer has a **secret maximum** it is willing to pay. Every seller has a **secret minimum** it will accept.
- Nobody knows anyone else's secret numbers. They can only shout prices ("I'll buy at 90", "I'll sell at 110").
- When a buyer's price meets a seller's price, they trade.
- One extra agent, the **analyst**, never trades. It listens to recent trade prices and to everyone's guess of
  what the price should be, and announces one combined estimate to the whole market.

Because we wrote the secret numbers ourselves, we can calculate the **fair price**: the single price where
supply meets demand. The agents never see it. **The question is whether they can find it just by trading and
talking**, and whether the analyst helps.

#### Why several agents instead of one?

We also tried the opposite: **one AI that is shown everybody's secret numbers** and asked to pick the price.
It got it wrong (it chose 115 when the fair price is 100) in 13 of 15 attempts. The market of many agents, each
knowing only its own numbers, did at least as well.
""")
    with right:
        if (FIGS / "architecture.png").exists():
            st.image(str(FIGS / "architecture.png"), caption="Who talks to whom")

    st.markdown("#### Results so far")
    board = [{"Setup": friendly(n), "Runs": by_name[n]["n_seeds"],
              "Gains captured": f"{by_name[n]['efficiency']:.0%}",
              "Buyers' share of the gains (fair: 48%)": f"{by_name[n]['buyer_share']:.0%}"}
             for n in SCOREBOARD if n in by_name]
    if board:
        top = [("Random traders", "baseline_zi_c_r6"), ("AI traders, no talking", "abl_no_comms_qwen3b_r6"),
               ("AI traders + analyst", "llm_full_qwen3b_r6")]
        for col, (label, key) in zip(st.columns(3), top):
            if key in by_name:
                col.metric(label, f"{by_name[key]['efficiency']:.0%}", help="Share of possible gains captured")
        fig = headline_chart(by_name)
        st.pyplot(fig); plt.close(fig)
        st.caption("Thin black lines show the uncertainty across repeats. Main market: 5 buyers, 5 sellers, "
                   "3 trading days of 6 rounds each.")
        st.dataframe(board, width="stretch", hide_index=True)
        st.caption("\"Gains captured\" = how much of the total possible benefit from trading actually happened. "
                   "100% means every trade that should happen did, and none that shouldn't.")

    with st.expander("Words used in this dashboard"):
        st.markdown("""
| Word | Plain meaning |
|---|---|
| **Fair price** (equilibrium, P\\*) | The price where the number of units buyers want equals the number sellers offer. We compute it from the secret numbers; agents never see it. |
| **Gains captured** (efficiency) | Each trade creates a benefit: the buyer's secret value minus the seller's secret cost. This is the share of the maximum possible total benefit that the market achieved. |
| **Round** | One turn. Every trader sees the same market and names a price (or passes) at the same time. |
| **Period** | One trading day, made of several rounds. At the end, everyone gets their units back and the day repeats, so agents can learn. |
| **Seed** | A run number. AI models and random traders don't behave identically every time, like re-dealing a deck of cards. Seed 0, 1, 2 are three separate repeats of the same experiment. We average them so one lucky or unlucky run doesn't mislead us. |
| **Buyers' share** | Of the total benefit created, the fraction that went to buyers. At the fair price it would be 48%; a higher number means prices were too low. |
| **Safety rule** (budget constraint) | The market refuses any order that would lose the trader money (buying above its value or selling below its cost) and records that the agent tried. |
| **Random traders** (ZI-C) | A standard baseline from economics: traders that pick random prices, limited only by the safety rule. If AI agents can't beat these, they add nothing. |
| **Analyst** | The coordinating agent. It sees only public trade prices and the guesses traders choose to post, never the secret numbers. |
""")

# ---------------------------------------------------------------------------------------------------------
with tab_live:
    st.markdown("Start a fresh market right now. The AI agents run on this laptop (model "
                f"`{MODEL}` through Ollama), so each decision takes a few seconds and nothing is pre-recorded.")
    c1, c2, c3 = st.columns(3)
    market_label = c1.selectbox("Market size", ["Small: 3 buyers, 3 sellers", "Full: 5 buyers, 5 sellers"])
    market_name = "pilot" if market_label.startswith("Small") else "symmetric"
    kind = c2.selectbox("Who trades?", ["AI agents (local model)", "Random traders (instant)"])
    use_ai = kind.startswith("AI")
    analyst_on = c3.toggle("Analyst agent switched on", value=True, disabled=not use_ai,
                           help="Turn it off to see the market without the coordinating agent.")
    c4, c5, c6, c7 = st.columns(4)
    n_periods = c4.number_input("Periods (trading days)", 1, 3, 1)
    n_rounds = c5.number_input("Rounds per period", 2, 10, 4)
    seed = c6.number_input("Seed (run number)", 0, 999, 0,
                           help="Change it to get a different repeat of the same experiment.")
    use_cache = c7.checkbox("Reuse saved AI answers", value=False, disabled=not use_ai,
                            help="Off = every answer is generated fresh. On = if this exact run was done before, "
                                 "it replays instantly from the cache.")

    live_cfg = load_market(ROOT / "market" / "configs" / f"{market_name}.yaml")
    n_traders = len(live_cfg.traders)
    if use_ai:
        st.caption(f"About {n_traders * n_rounds * n_periods} AI decisions, roughly "
                   f"{max(1, round(n_traders * n_rounds * n_periods * 15 / 60))} minutes on this laptop.")
    with st.expander("The secret numbers for this market (agents only see their own row)"):
        sc1, sc2 = st.columns([3, 2])
        sc1.dataframe(secrets_table(live_cfg), width="stretch", hide_index=True)
        fig = supply_demand_chart(live_cfg)
        sc2.pyplot(fig); plt.close(fig)
        sc2.caption("Line up buyers from most to least eager and sellers from cheapest to dearest. "
                    "Where the two staircases cross is the fair price.")
        e0 = compute_equilibrium(live_cfg)
        st.caption(f"Fair price: {e0.price_low:g}" + (f" to {e0.price_high:g}" if e0.price_high != e0.price_low else "")
                   + f" · units that should trade per period: {e0.quantity} · maximum total gain per period: {e0.max_surplus:g}")

    start = st.button("Start live run", type="primary")
    if start and use_ai and LIVE_BACKEND == "ollama" and not ollama_ready():
        st.error(f"Ollama is not running or the model `{MODEL}` is missing. Open the Ollama app "
                 f"(or run `ollama pull {MODEL}`) and try again. The Replay tab works without it.")
        start = False

    if start:
        exp = {"name": f"live_{market_name}", "market": f"market/configs/{market_name}.yaml",
               "session": {"n_periods": int(n_periods), "rounds_per_period": int(n_rounds), "enforce_budget": True,
                           "max_workers": 1},
               "traders": ({"type": "llm", "personas": "neutral", "memory": True, "chat": False} if use_ai
                           else {"type": "zi_c"}),
               "analyst": {"enabled": bool(analyst_on and use_ai), "mode": "rule"},
               "llm": {"backend": LIVE_BACKEND, "model": MODEL, "effort": "low", "use_cache": bool(use_cache)}}
        max_total = sum(compute_equilibrium(live_cfg.for_period(p)).max_surplus for p in range(int(n_periods)))
        total_decisions = n_traders * int(n_rounds) * int(n_periods)
        status, bar = st.empty(), st.progress(0.0)
        k1, k2, k3 = st.columns(3)
        m_trades, m_gain, m_analyst = k1.empty(), k2.empty(), k3.empty()
        chart = st.empty()
        col_feed, col_table = st.columns([2, 3])
        col_feed.markdown("**Latest decisions**")
        feed = col_feed.empty()
        col_table.markdown("**Last completed round**")
        story = col_table.empty()
        table = col_table.empty()
        recent: list[str] = []
        t_start = time.time()

        def on_decision(period, rnd, n_done, n_active, tr, d):
            done = (period * int(n_rounds) + rnd) * n_traders + n_done
            bar.progress(min(1.0, done / total_decisions))
            status.info(f"Period {period + 1} of {int(n_periods)}, round {rnd + 1} of {int(n_rounds)}: "
                        f"{n_done} of {n_active} traders have decided ({time.time() - t_start:.0f} s elapsed)")
            what = "value" if tr.role == "buyer" else "cost"
            said = "passes" if d.action == "pass" or d.price is None else f"{d.action}s at {d.price:g}"
            why = f" — *{d.reasoning.strip()}*" if getattr(d, "reasoning", "") else ""
            recent.insert(0, f"**{tr.agent_id}** ({tr.role}, secret {what} {tr.next_unit}) {said}{why}")
            feed.markdown("\n\n".join(recent[:6]))

        def on_round(period, rnd, auc):
            fig = price_chart(live_cfg, auc.trades, int(n_periods))
            chart.pyplot(fig); plt.close(fig)
            gained = sum(t["surplus"] for t in auc.trades)
            m_trades.metric("Trades so far", len(auc.trades))
            m_gain.metric("Gains captured so far", f"{gained / max_total:.0%}" if max_total else "-")
            if auc.analyst and auc.analyst.last_estimate is not None:
                m_analyst.metric("Analyst's price estimate", f"{auc.analyst.last_estimate:g}")
            told = trade_story([t for t in auc.trades if t["period"] == period and t["round"] == rnd])
            story.markdown("\n\n".join(told) if told else "*No trade this round: no buyer's price met a seller's price.*")
            table.dataframe(order_rows([o for o in auc.orders if o["period"] == period and o["round"] == rnd]),
                            width="stretch", hide_index=True)

        metrics = run_one(exp, int(seed), RESULTS / "_live", on_decision=on_decision, on_round=on_round)
        bar.progress(1.0)
        status.success(f"Finished in {time.time() - t_start:.0f} s.")
        st.session_state["live_result"] = {"exp": exp, "seed": int(seed), "metrics": metrics,
                                           "market": market_name, "ai": use_ai}

    res = st.session_state.get("live_result")
    if res and not start:
        st.info("Result of the last live run (press Start for a new one).")
    if res:
        m = res["metrics"]
        run_dir = RESULTS / "_live" / res["exp"]["name"] / f"seed_{res['seed']}"
        r1, r2, r3, r4 = st.columns(4)
        r1.metric("Gains captured", f"{m['efficiency']:.0%}")
        r2.metric("Trades", m["n_trades"])
        r3.metric("Buyers' share", f"{m['buyer_share']:.0%}" if m["n_trades"] else "-",
                  help=f"At the fair price it would be {m['buyer_share_ce']:.0%}.")
        r4.metric("AI decisions made", m.get("llm_calls", 0))
        if not start and (run_dir / "trades.jsonl").exists():
            cfg_done = load_market_json(run_dir / "market.json")
            done_trades = [json.loads(l) for l in open(run_dir / "trades.jsonl")]
            fig = price_chart(cfg_done, done_trades, len(m["per_period"]))
            st.pyplot(fig); plt.close(fig)
        base = by_name.get("pilot_zi_c_r6" if res["market"] == "pilot" else "baseline_zi_c_r6")
        st.markdown(verdict(m, base if res["ai"] else None))
        if base and res["ai"]:
            st.caption(f"For comparison, random traders capture {base['efficiency']:.0%} on this market on average "
                       f"(6 rounds per period, {base['n_seeds']} runs). One live run is a single repeat, so it can land "
                       "above or below the averages on the first tab.")

# ---------------------------------------------------------------------------------------------------------
with tab_replay:
    if not runs_by_exp:
        st.info("No saved runs yet. Use the live tab, or run an experiment with `--backend ollama`.")
    else:
        st.markdown("Step through a run that was recorded earlier. Nothing is computed here, so it always works.")
        c1, c2 = st.columns([3, 1])
        names = sorted(runs_by_exp, key=lambda n: (n not in FRIENDLY, list(FRIENDLY).index(n) if n in FRIENDLY else 0, n))
        exp_name = c1.selectbox("Which setup?", names, format_func=friendly)
        seed_dir = c2.selectbox("Seed (which repeat)", runs_by_exp[exp_name],
                                format_func=lambda s: s.replace("seed_", "repeat #"),
                                help="Each seed is a separate repeat of the same experiment.")
        run = RESULTS / exp_name / seed_dir
        cfg = load_market_json(run / "market.json")
        trades = [json.loads(l) for l in open(run / "trades.jsonl")]
        orders = [json.loads(l) for l in open(run / "orders.jsonl")]
        msgs = [json.loads(l) for l in open(run / "messages.jsonl")]
        metrics = json.loads((run / "metrics.json").read_text())
        run_cfg = yaml.safe_load(open(run / "config.yaml"))
        model = run_cfg.get("llm", {}).get("model", "-") if metrics.get("backend") not in (None, "none") else "no AI model"
        st.caption(f"Technical name: `{exp_name}` · model: {model} · market: {cfg.name} · "
                   f"{len(metrics['per_period'])} periods × "
                   f"{run_cfg.get('session', {}).get('rounds_per_period', 10)} rounds")

        m1, m2, m3, m4, m5 = st.columns(5)
        m1.metric("Gains captured", f"{metrics['efficiency']:.0%}",
                  help="Share of the maximum possible benefit from trade that actually happened (efficiency).")
        m2.metric("Trades", metrics["n_trades"],
                  help=f"Units that should trade at the fair price: {sum(p['eq_quantity'] for p in metrics['per_period'])}.")
        m3.metric("Typical distance from fair price", f"{metrics['price_rmsd']:.0f}",
                  help="How far trade prices were from the fair price, on average (RMSD). Lower is better.")
        bs = metrics.get("buyer_share")
        m4.metric("Buyers' share", f"{bs:.0%}" if bs is not None else "-",
                  help=f"At the fair price it would be {metrics.get('buyer_share_ce', float('nan')):.0%}.")
        m5.metric("AI decisions", metrics.get("llm_calls", 0))

        rounds_here = run_cfg.get("session", {}).get("rounds_per_period", 10)
        is_baseline = metrics.get("backend") in (None, "none")
        st.markdown(verdict(metrics, None if is_baseline else random_baseline(by_name, cfg.name, rounds_here)))

        if trades:
            step = st.slider("Drag to replay trade by trade", 1, len(trades), len(trades)) if len(trades) > 1 else 1
            shown = trades[:step]
            fig = price_chart(cfg, shown, len(metrics["per_period"]))
            st.pyplot(fig); plt.close(fig)
            st.caption("Each dot is one trade. The shaded band is the fair price, which the agents cannot see. "
                       "Dots inside the band mean the market found the right price.")
            cur = shown[-1]
            st.subheader(f"Period {cur['period'] + 1}, round {cur['round'] + 1}: what happened")
            for line in trade_story([t for t in shown if t["period"] == cur["period"] and t["round"] == cur["round"]]):
                st.markdown(line)
            st.markdown("**What every trader did this round**")
            st.dataframe(order_rows([o for o in orders if o["period"] == cur["period"] and o["round"] == cur["round"]]),
                         width="stretch", hide_index=True)
            said = [m for m in msgs if m["period"] == cur["period"] and m["round"] <= cur["round"]
                    and m["channel"] in ("analyst", "chat")][-4:]
            if said:
                st.subheader("What the analyst announced")
                for m in said:
                    st.markdown(f"Round {m['round'] + 1}: {m['content']}")
        else:
            st.warning("This run produced no trades.")
        with st.expander("The secret numbers for this market"):
            sc1, sc2 = st.columns([3, 2])
            sc1.dataframe(secrets_table(cfg), width="stretch", hide_index=True)
            fig = supply_demand_chart(cfg)
            sc2.pyplot(fig); plt.close(fig)

# ---------------------------------------------------------------------------------------------------------
with tab_compare:
    st.markdown("Every setup, averaged over its repeats (seeds).")
    show_all = st.checkbox("Also show development and test runs", value=False)
    table_rows = [{"Setup": friendly(r["experiment"]), "Repeats": r["n_seeds"],
                   "Gains captured": round(r["efficiency"], 3), "± (95%)": round(r["efficiency_ci95"], 3),
                   "Distance from fair price": round(r["price_rmsd"], 1),
                   "Buyers' share": round(r["buyer_share"], 2),
                   "Round when prices settle": round(r["converge_round"], 1)}
                  for r in rows if show_all or r["experiment"] in FRIENDLY]
    st.dataframe(table_rows, width="stretch", hide_index=True)
    st.caption("\"Round when prices settle\" = the first round after which every trade is within 10% of the fair "
               "price. A value above the number of rounds means prices never settled.")
    captions = {"efficiency_by_period.png": "Gains captured in each period",
                "convergence_by_round.png": "How far prices are from the fair price, round by round",
                "surplus_split.png": "Who got the gains: buyers or sellers",
                "prompt_fix_before_after.png": "Before and after fixing the agents' instructions"}
    cols = st.columns(2)
    for i, (name, cap) in enumerate(captions.items()):
        if (FIGS / name).exists():
            cols[i % 2].image(str(FIGS / name), caption=cap)
