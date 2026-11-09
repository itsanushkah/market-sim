"""Common agent interface so the auctioneer treats LLM, ZI and other traders identically."""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class Decision:
    action: str                 # "bid" | "ask" | "pass"
    price: float | None = None
    belief: float | None = None  # trader's estimate of the equilibrium price (posted to the bus)
    message: str | None = None   # optional cheap-talk message (only delivered if "chat" channel is on)
    reasoning: str = ""
    meta: dict = field(default_factory=dict)


class Trader:
    kind = "base"

    def __init__(self, agent_id: str, role: str, units: list[float], rng=None):
        self.agent_id = agent_id
        self.role = role
        self.units = list(units)
        self.traded = 0
        self.profit = 0.0
        self.rng = rng

    # --- lifecycle -------------------------------------------------------
    def on_period_start(self, period: int, units: list[float]) -> None:
        self.units = list(units)
        self.traded = 0

    def on_trade(self, price: float) -> float:
        """Record a trade of the next unit; return the surplus earned on it."""
        unit = self.units[self.traded]
        surplus = (unit - price) if self.role == "buyer" else (price - unit)
        self.traded += 1
        self.profit += surplus
        return surplus

    def on_period_end(self, period: int, summary: dict) -> None:
        pass

    # --- state -----------------------------------------------------------
    @property
    def next_unit(self) -> float | None:
        return self.units[self.traded] if self.traded < len(self.units) else None

    @property
    def active(self) -> bool:
        return self.next_unit is not None

    @property
    def side(self) -> str:
        return "bid" if self.role == "buyer" else "ask"

    def decide(self, obs: dict) -> Decision:
        raise NotImplementedError
