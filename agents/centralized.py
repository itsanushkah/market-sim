"""Centralized (single-agent) baselines.

- OraclePlanner: computes the exact competitive equilibrium. Upper bound (efficiency = 1.0).
- LLMPlanner: ONE LLM sees every trader's private values and costs and picks a single market-clearing
  price. All units whose value >= p >= cost then trade at p. This answers: "does a single omniscient
  LLM do better or worse than many decentralized LLM agents with private information?"
"""
from __future__ import annotations

from market.config import MarketConfig
from market.equilibrium import compute_equilibrium
from llm.client import LLMClient

SCHEMA = {
    "type": "object",
    "properties": {
        "price": {"type": "number", "description": "The single price at which the market will clear."},
        "reasoning": {"type": "string"},
    },
    "required": ["price", "reasoning"],
    "additionalProperties": False,
}

SYSTEM = ("You are a central planner for a market. You can see every buyer's private unit values and every "
          "seller's private unit costs. Choose ONE price; every buyer unit with value >= price and every seller "
          "unit with cost <= price will trade at that price (matched highest-value to lowest-cost). Choose the price "
          "that maximises total surplus (sum of value minus cost over traded units). Respond only with the requested JSON.")


def clear_at_price(cfg: MarketConfig, price: float) -> list[tuple[str, str, float, float, float]]:
    """Uniform-price clearing. Returns (buyer_id, seller_id, price, value, cost) per traded unit."""
    bunits = sorted(((v, b.agent_id) for b in cfg.buyers for v in b.units if v >= price), reverse=True)
    sunits = sorted((c, s.agent_id) for s in cfg.sellers for c in s.units if c <= price)
    n = min(len(bunits), len(sunits))
    return [(bunits[i][1], sunits[i][1], price, bunits[i][0], sunits[i][0]) for i in range(n)]


class OraclePlanner:
    kind = "oracle"

    def choose_price(self, cfg: MarketConfig) -> tuple[float, str]:
        return compute_equilibrium(cfg).price_mid, "exact equilibrium"


class LLMPlanner:
    kind = "centralized_llm"

    def __init__(self, llm: LLMClient):
        self.llm = llm

    def choose_price(self, cfg: MarketConfig) -> tuple[float, str]:
        lines = [f"Buyer {b.agent_id} unit values: {b.units}" for b in cfg.buyers]
        lines += [f"Seller {s.agent_id} unit costs: {s.units}" for s in cfg.sellers]
        lines.append(f"Allowed price range: [{cfg.price_min}, {cfg.price_max}].")
        mid = compute_equilibrium(cfg).price_mid
        out = self.llm.complete_json(agent_id="planner", system=SYSTEM, user="\n".join(lines), schema=SCHEMA,
                                     mock_fn=lambda: {"price": mid, "reasoning": "mock: exact"})
        if out is None:
            return (cfg.price_min + cfg.price_max) / 2, "llm_error"
        return float(out["price"]), out.get("reasoning", "")
