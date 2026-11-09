"""Continuous double auction order book.

Rules (kept simple and documented so they can go in the report):
- Each agent has at most one standing order; a new order replaces the old one.
- An incoming bid >= best ask (or ask <= best bid) trades immediately at the *standing* order's price.
- Price-time priority among standing orders.
- Optionally the whole book is cleared after each trade (Gode & Sunder 1993 convention).
"""
from __future__ import annotations

from dataclasses import dataclass, asdict


@dataclass
class Order:
    agent_id: str
    side: str          # "bid" | "ask"
    price: float
    seq: int = 0       # arrival sequence number, for time priority


@dataclass
class Trade:
    buyer_id: str
    seller_id: str
    price: float
    period: int
    round: int
    seq: int

    def to_dict(self) -> dict:
        return asdict(self)


class OrderBook:
    def __init__(self, clear_after_trade: bool = True):
        self.bids: list[Order] = []
        self.asks: list[Order] = []
        self.clear_after_trade = clear_after_trade
        self._seq = 0

    def best_bid(self) -> Order | None:
        return max(self.bids, key=lambda o: (o.price, -o.seq), default=None)

    def best_ask(self) -> Order | None:
        return min(self.asks, key=lambda o: (o.price, o.seq), default=None)

    def cancel(self, agent_id: str) -> None:
        self.bids = [o for o in self.bids if o.agent_id != agent_id]
        self.asks = [o for o in self.asks if o.agent_id != agent_id]

    def clear(self) -> None:
        self.bids, self.asks = [], []

    def submit(self, order: Order) -> tuple[str, str, float] | None:
        """Submit an order. Returns (buyer_id, seller_id, price) if it trades, else None."""
        self._seq += 1
        order.seq = self._seq
        self.cancel(order.agent_id)
        if order.side == "bid":
            ask = self.best_ask()
            if ask is not None and order.price >= ask.price and ask.agent_id != order.agent_id:
                self.asks.remove(ask)
                return self._after_trade(order.agent_id, ask.agent_id, ask.price)
            self.bids.append(order)
        elif order.side == "ask":
            bid = self.best_bid()
            if bid is not None and order.price <= bid.price and bid.agent_id != order.agent_id:
                self.bids.remove(bid)
                return self._after_trade(bid.agent_id, order.agent_id, bid.price)
            self.asks.append(order)
        else:
            raise ValueError(f"bad side {order.side!r}")
        return None

    def _after_trade(self, buyer: str, seller: str, price: float):
        if self.clear_after_trade:
            self.clear()
        return buyer, seller, price

    def snapshot(self) -> dict:
        bb, ba = self.best_bid(), self.best_ask()
        return {"best_bid": bb.price if bb else None, "best_ask": ba.price if ba else None,
                "n_bids": len(self.bids), "n_asks": len(self.asks)}
