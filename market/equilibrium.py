"""Competitive equilibrium of a step supply/demand market: the ground truth for evaluation."""
from __future__ import annotations

from dataclasses import dataclass

from market.config import MarketConfig


@dataclass
class Equilibrium:
    quantity: int
    price_low: float
    price_high: float
    max_surplus: float

    @property
    def price_mid(self) -> float:
        return (self.price_low + self.price_high) / 2


def demand_supply(cfg: MarketConfig) -> tuple[list[float], list[float]]:
    demand = sorted((v for b in cfg.buyers for v in b.units), reverse=True)
    supply = sorted(c for s in cfg.sellers for c in s.units)
    return demand, supply


def compute_equilibrium(cfg: MarketConfig) -> Equilibrium:
    demand, supply = demand_supply(cfg)
    q = 0
    while q < min(len(demand), len(supply)) and demand[q] >= supply[q]:
        q += 1
    if q == 0:
        lo = supply[0] if supply else cfg.price_min
        hi = demand[0] if demand else cfg.price_max
        return Equilibrium(0, min(lo, hi), max(lo, hi), 0.0)
    # Any price p clears q units iff: demand[q-1] >= p >= supply[q-1], and the (q+1)th units don't want to trade at p.
    low = supply[q - 1]
    high = demand[q - 1]
    if q < len(demand):
        low = max(low, demand[q])
    if q < len(supply):
        high = min(high, supply[q])
    surplus = sum(demand[:q]) - sum(supply[:q])
    return Equilibrium(q, float(low), float(high), float(surplus))
