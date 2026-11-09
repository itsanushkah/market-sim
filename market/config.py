"""Supply/demand configurations: who holds which private values (buyers) and costs (sellers).

A market config is a list of traders, each with a role and a list of unit values/costs.
Buyers must trade their highest-value unit first; sellers their lowest-cost unit first.
Configs can be loaded from YAML (market/configs/*.yaml) or generated.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
import yaml

BUYER, SELLER = "buyer", "seller"


@dataclass
class TraderSpec:
    agent_id: str
    role: str                      # "buyer" | "seller"
    units: list[float]             # values (buyer, desc) or costs (seller, asc)

    def __post_init__(self):
        self.units = sorted(self.units, reverse=(self.role == BUYER))


@dataclass
class MarketConfig:
    name: str
    traders: list[TraderSpec]
    price_min: float = 0.0
    price_max: float = 200.0
    # Optional demand/supply shock: at the start of `shock_period`, every unit is shifted by `shock_delta`.
    shock_period: int | None = None
    shock_delta: float = 0.0
    meta: dict = field(default_factory=dict)

    @property
    def buyers(self) -> list[TraderSpec]:
        return [t for t in self.traders if t.role == BUYER]

    @property
    def sellers(self) -> list[TraderSpec]:
        return [t for t in self.traders if t.role == SELLER]

    def for_period(self, period: int) -> "MarketConfig":
        """Return the config in force during `period` (applies the shock if any)."""
        if self.shock_period is None or period < self.shock_period:
            return self
        shifted = [TraderSpec(t.agent_id, t.role, [u + self.shock_delta for u in t.units]) for t in self.traders]
        return MarketConfig(self.name, shifted, self.price_min, self.price_max, None, 0.0, self.meta)


def load_market(path: str | Path) -> MarketConfig:
    with open(path) as f:
        raw = yaml.safe_load(f)
    if "generator" in raw:
        return generate_market(**raw["generator"], name=raw.get("name", Path(path).stem),
                               shock_period=raw.get("shock_period"), shock_delta=raw.get("shock_delta", 0.0))
    traders = [TraderSpec(t["id"], t["role"], list(t["units"])) for t in raw["traders"]]
    return MarketConfig(raw.get("name", Path(path).stem), traders, raw.get("price_min", 0.0),
                        raw.get("price_max", 200.0), raw.get("shock_period"), raw.get("shock_delta", 0.0))


def generate_market(n_buyers: int = 5, n_sellers: int = 5, units_per_trader: int = 3,
                    value_low: float = 60, value_high: float = 160, cost_low: float = 40,
                    cost_high: float = 140, seed: int = 0, name: str = "generated",
                    shock_period: int | None = None, shock_delta: float = 0.0) -> MarketConfig:
    """Random integer values/costs drawn uniformly. Seeded so every condition sees the same market."""
    rng = np.random.default_rng(seed)
    traders = []
    for i in range(n_buyers):
        traders.append(TraderSpec(f"B{i}", BUYER, rng.integers(value_low, value_high, units_per_trader).tolist()))
    for i in range(n_sellers):
        traders.append(TraderSpec(f"S{i}", SELLER, rng.integers(cost_low, cost_high, units_per_trader).tolist()))
    hi = max(value_high, cost_high)
    return MarketConfig(name, traders, 0.0, float(hi + 40), shock_period, shock_delta, {"seed": seed})
