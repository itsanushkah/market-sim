"""Analyst agent: the coordination layer. It never trades.

Each round it reads (a) public trade prices and (b) every trader's posted belief about the equilibrium
price (the "beliefs" channel), resolves the disagreement into one consensus estimate, and broadcasts it
on the "analyst" channel. Traders see the broadcast next round.

mode="rule": consensus = median of recent trades (if any) blended with the median belief; spread = IQR.
mode="llm":  an LLM writes the estimate and a one-line market summary from the same inputs.
"""
from __future__ import annotations

import numpy as np

from comms.bus import Message, MessageBus
from llm.client import LLMClient

SCHEMA = {
    "type": "object",
    "properties": {
        "estimate": {"type": "number", "description": "Best estimate of the competitive equilibrium price."},
        "summary": {"type": "string", "description": "One or two sentences for traders."},
    },
    "required": ["estimate", "summary"],
    "additionalProperties": False,
}

SYSTEM = ("You are a market analyst observing a double auction. You do not trade. "
          "Traders have posted their private estimates of the equilibrium price; these may disagree. "
          "Combine them with observed trade prices into a single best estimate of the competitive equilibrium price "
          "and a short neutral summary. Respond only with the requested JSON.")


class Analyst:
    agent_id = "analyst"

    def __init__(self, bus: MessageBus, mode: str = "rule", llm: LLMClient | None = None, trade_weight: float = 0.6):
        self.bus, self.mode, self.llm = bus, mode, llm
        self.trade_weight = trade_weight
        self.last_estimate: float | None = None
        self.history: list[dict] = []

    def observe_round(self, period: int, rnd: int, prices: list[float]) -> float | None:
        beliefs = [m.data["belief"] for m in self.bus.read("beliefs")
                   if m.period == period and m.round == rnd and m.data.get("belief") is not None]
        recent = prices[-5:]
        spread = float(np.subtract(*np.percentile(beliefs, [75, 25]))) if len(beliefs) >= 2 else None

        if self.mode == "llm" and self.llm is not None:
            est, summary = self._llm_estimate(period, rnd, recent, beliefs, spread)
        else:
            est, summary = self._rule_estimate(recent, beliefs, spread)
        if est is None:
            return self.last_estimate
        self.last_estimate = est
        self.history.append({"period": period, "round": rnd, "estimate": est, "spread": spread,
                             "n_beliefs": len(beliefs)})
        self.bus.publish(Message(self.agent_id, "analyst", summary, period, rnd,
                                 {"estimate": est, "belief_spread": spread}))
        return est

    def _rule_estimate(self, recent, beliefs, spread):
        parts, weights = [], []
        if recent:
            parts.append(float(np.median(recent))); weights.append(self.trade_weight)
        if beliefs:
            parts.append(float(np.median(beliefs))); weights.append(1 - self.trade_weight)
        if not parts:
            return None, ""
        est = round(float(np.average(parts, weights=weights)), 2)
        spread_txt = f"; traders disagree by about {spread:.1f} (IQR)" if spread is not None else ""
        return est, f"Consensus equilibrium estimate: {est}{spread_txt}. Recent trades: {recent}."

    def _llm_estimate(self, period, rnd, recent, beliefs, spread):
        user = (f"Period {period + 1}, round {rnd + 1}.\nRecent trade prices: {recent}.\n"
                f"Trader belief estimates this round: {sorted(round(b, 2) for b in beliefs)}.\n"
                f"Your previous estimate: {self.last_estimate}.")
        fallback = self._rule_estimate(recent, beliefs, spread)
        out = self.llm.complete_json(agent_id=self.agent_id, system=SYSTEM, user=user, schema=SCHEMA,
                                     mock_fn=lambda: {"estimate": fallback[0] or 0.0, "summary": fallback[1]})
        if out is None or fallback[0] is None:
            return fallback
        return round(float(out["estimate"]), 2), out["summary"]
