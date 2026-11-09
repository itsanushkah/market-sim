"""LLM-driven trader. Each round it sees its private unit value/cost, the public book, recent trades,
analyst broadcasts (and optional chat), plus its own memory of past periods, and returns a structured action.
"""
from __future__ import annotations

import json

from agents.base import Decision, Trader
from agents.personas import PERSONAS
from llm.client import LLMClient

SCHEMA = {
    "type": "object",
    "properties": {
        "action": {"type": "string", "enum": ["bid", "ask", "pass"]},
        "price": {"type": "number", "description": "Order price; ignored if action is pass."},
        "belief": {"type": "number", "description": "Your estimate of the market's equilibrium price."},
        "message": {"type": "string", "description": "Optional short public message to other traders (may be empty)."},
        "reasoning": {"type": "string", "description": "At most 15 words explaining the action."},
    },
    "required": ["action", "price", "belief", "message", "reasoning"],
    "additionalProperties": False,
}

RULES = """You are trading in a continuous double auction for a single good.
- Buyers submit bids; sellers submit asks. A bid >= the best ask (or ask <= the best bid) trades immediately at the standing order's price.
- You trade one unit at a time. Buyers earn (unit value - price); sellers earn (price - unit cost).
- Your unit values/costs are private. Other traders cannot see them.
- Each period has a fixed number of rounds; untraded units at the end of a period earn nothing.
- Your goal is to maximise your total profit across all periods.
- Buyers: never bid above your unit value. Sellers: never ask below your unit cost. That trade loses money.
- Pricing exactly at your own value/cost earns zero profit; aim for a margin while still trading.
- "belief" is your estimate of the price at which supply meets demand. It must be a realistic price inside the
  allowed range, never 0.
- The analyst's estimate is a summary of other traders' guesses. It can be wrong; check it against your own
  value/cost and the actual order book.
Respond only with the requested JSON."""


class LLMTrader(Trader):
    kind = "llm"

    def __init__(self, agent_id, role, units, rng, llm: LLMClient, persona: str = "neutral",
                 memory: bool = True, chat: bool = False, price_min: float = 0, price_max: float = 200):
        super().__init__(agent_id, role, units, rng)
        self.llm = llm
        self.persona = persona
        self.use_memory = memory
        self.chat = chat
        self.price_min, self.price_max = price_min, price_max
        self.memory: list[str] = []
        self._period_trades: list[float] = []

    # ------------------------------------------------------------------
    def system_prompt(self) -> str:
        return f"{RULES}\n\nYou are a {self.role.upper()}. {PERSONAS[self.persona]['prompt']}"

    def user_prompt(self, obs: dict) -> str:
        unit_word = "value" if self.role == "buyer" else "cost"
        lines = [
            f"Period {obs['period'] + 1} of {obs['n_periods']}, round {obs['round'] + 1} of {obs['rounds_per_period']}.",
            f"Your next unit {unit_word}: {self.next_unit}. Remaining unit {unit_word}s this period: {self.units[self.traded:]}.",
            f"Units traded this period: {self.traded}, at prices {self._period_trades}.",
            f"Order book: best bid = {obs['best_bid']}, best ask = {obs['best_ask']}.",
            f"Recent trade prices (oldest to newest): {obs['recent_prices']}.",
            f"Allowed price range: [{self.price_min}, {self.price_max}].",
        ]
        lines.append(self._profit_preview(obs))
        if obs.get("messages"):
            lines.append("Messages:")
            for m in obs["messages"]:
                lines.append(f"  [{m['channel']}] {m['sender']}: {m['content']}")
        if self.use_memory and self.memory:
            lines.append("Your notes from previous periods:")
            lines += [f"  - {n}" for n in self.memory[-3:]]
        allowed = "bid" if self.role == "buyer" else "ask"
        lines.append(f'Choose action "{allowed}" or "pass".'
                     + (" You may include a short public message." if self.chat else ' Leave "message" empty.'))
        return "\n".join(lines)

    def _profit_preview(self, obs: dict) -> str:
        """Spell out the arithmetic small models get wrong: what you'd earn by accepting the current quote."""
        unit = self.next_unit
        if self.role == "buyer":
            q = obs["best_ask"]
            if q is None:
                return f"No ask to accept yet. Any bid above {unit} would lose money."
            p = unit - q
            verdict = "a profit" if p > 0 else ("zero profit" if p == 0 else "a LOSS")
            return f"Bidding {q} now would buy at the best ask: {unit} - {q} = {p:g}, {verdict}."
        q = obs["best_bid"]
        if q is None:
            return f"No bid to accept yet. Any ask below {unit} would lose money."
        p = q - unit
        verdict = "a profit" if p > 0 else ("zero profit" if p == 0 else "a LOSS")
        return f"Asking {q} now would sell at the best bid: {q} - {unit} = {p:g}, {verdict}."

    # ------------------------------------------------------------------
    def decide(self, obs: dict) -> Decision:
        if not self.active:
            return Decision("pass")
        out = self.llm.complete_json(agent_id=self.agent_id, system=self.system_prompt(),
                                     user=self.user_prompt(obs), schema=SCHEMA,
                                     mock_fn=lambda: self._mock_policy(obs))
        if out is None:
            return Decision("pass", reasoning="llm_error", meta={"error": True})
        action = out.get("action", "pass")
        if action not in (self.side, "pass"):
            return Decision("pass", belief=out.get("belief"), reasoning=out.get("reasoning", ""),
                            meta={"invalid_action": action})
        return Decision(action, _num(out.get("price")), _num(out.get("belief")),
                        (out.get("message") or None) if self.chat else None, out.get("reasoning", ""))

    def on_period_start(self, period, units):
        super().on_period_start(period, units)
        self._period_trades = []

    def on_trade(self, price):
        self._period_trades.append(price)
        return super().on_trade(price)

    def on_period_end(self, period, summary):
        if not self.use_memory:
            return
        prices = summary.get("prices", [])
        avg = round(sum(prices) / len(prices), 2) if prices else None
        self.memory.append(
            f"Period {period + 1}: market traded {len(prices)} units, avg price {avg}, range "
            f"{(min(prices), max(prices)) if prices else None}. You traded {len(self._period_trades)}/{len(self.units)} "
            f"units at {self._period_trades}; cumulative profit {round(self.profit, 2)}.")

    # ------------------------------------------------------------------
    def _mock_policy(self, obs: dict) -> dict:
        """Offline stand-in for the LLM: anchor on the analyst estimate / recent prices, shade by persona margin,
        accept the opposite side's quote when it is within the anchor. Deterministic given the rng."""
        unit = self.next_unit
        margin = PERSONAS[self.persona]["margin"]
        anchor = obs.get("analyst_estimate") or (sum(obs["recent_prices"][-5:]) / len(obs["recent_prices"][-5:])
                                                 if obs["recent_prices"] else unit)
        urgency = (obs["round"] + 1) / obs["rounds_per_period"]
        noise = float(self.rng.normal(0, 2))
        if self.role == "buyer":
            best_ask = obs["best_ask"]
            if best_ask is not None and best_ask <= min(unit, anchor * (1 + margin * urgency)):
                price = best_ask
            else:
                price = min(unit, anchor * (1 - margin * (1 - urgency)) + noise)
            return {"action": "bid", "price": round(price, 2), "belief": round(anchor, 2), "message": "",
                    "reasoning": "mock"}
        best_bid = obs["best_bid"]
        if best_bid is not None and best_bid >= max(unit, anchor * (1 - margin * urgency)):
            price = best_bid
        else:
            price = max(unit, anchor * (1 + margin * (1 - urgency)) + noise)
        return {"action": "ask", "price": round(price, 2), "belief": round(anchor, 2), "message": "",
                "reasoning": "mock"}


def _num(x):
    try:
        return float(x) if x is not None else None
    except (TypeError, ValueError):
        return None
