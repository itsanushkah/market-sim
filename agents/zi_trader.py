"""Zero-Intelligence traders (Gode & Sunder 1993): the classic non-LLM baseline.

ZI-C: random prices subject to the budget constraint (never trade at a loss).
ZI-U: unconstrained random prices (lower bound on how badly a market can do).
"""
from __future__ import annotations

from agents.base import Decision, Trader


class ZITrader(Trader):
    kind = "zi"

    def __init__(self, agent_id, role, units, rng, price_min: float, price_max: float, constrained: bool = True):
        super().__init__(agent_id, role, units, rng)
        self.price_min, self.price_max = price_min, price_max
        self.constrained = constrained
        self.kind = "zi_c" if constrained else "zi_u"

    def decide(self, obs: dict) -> Decision:
        unit = self.next_unit
        if unit is None:
            return Decision("pass")
        if self.role == "buyer":
            hi = unit if self.constrained else self.price_max
            price = float(self.rng.uniform(self.price_min, hi))
        else:
            lo = unit if self.constrained else self.price_min
            price = float(self.rng.uniform(lo, self.price_max))
        return Decision(self.side, round(price, 2))
