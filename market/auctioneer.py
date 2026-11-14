"""Auctioneer: runs a multi-period continuous double auction.

Each round:
  1. Every active trader observes the SAME snapshot (book, recent trades, analyst broadcast, chat).
  2. All traders decide in parallel (threads, so LLM calls overlap).
  3. Beliefs / chat messages are posted to the bus.
  4. Orders enter the book in a random order; crossing orders trade.
  5. The analyst (if present) reads the round and broadcasts a consensus estimate.
At the end of each period, traders get a summary (used for memory) and unit endowments reset.
"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor

from agents.base import Decision, Trader
from comms.bus import Message, MessageBus
from market.config import MarketConfig
from market.order_book import Order, OrderBook, Trade


class Auctioneer:
    def __init__(self, cfg: MarketConfig, traders: list[Trader], bus: MessageBus, rng, analyst=None,
                 n_periods: int = 3, rounds_per_period: int = 10, enforce_budget: bool = True,
                 clear_after_trade: bool = True, max_workers: int = 8,
                 on_decision=None, on_round=None):
        self.cfg, self.traders, self.bus, self.rng, self.analyst = cfg, traders, bus, rng, analyst
        self.n_periods, self.rounds = n_periods, rounds_per_period
        self.enforce_budget = enforce_budget
        self.book = OrderBook(clear_after_trade)
        self.max_workers = max_workers
        # Optional observers for a live UI. Both are called from the thread that called run().
        #   on_decision(period, round, n_done, n_active, trader, decision)   as each agent's decision arrives
        #   on_round(period, round, auctioneer)                              after orders are matched
        self.on_decision, self.on_round = on_decision, on_round
        self.by_id = {t.agent_id: t for t in traders}
        self.trades: list[dict] = []
        self.orders: list[dict] = []

    def run(self) -> dict:
        for period in range(self.n_periods):
            pcfg = self.cfg.for_period(period)
            specs = {t.agent_id: t for t in pcfg.traders}
            for tr in self.traders:
                tr.on_period_start(period, specs[tr.agent_id].units)
            self.book.clear()
            period_prices: list[float] = []
            for rnd in range(self.rounds):
                self._run_round(period, rnd, period_prices)
            summary = {"prices": list(period_prices)}
            print(f"  period {period + 1}/{self.n_periods}: {len(period_prices)} trades, "
                  f"prices {[round(x, 1) for x in period_prices]}", flush=True)
            for tr in self.traders:
                tr.on_period_end(period, summary)
        return {"trades": self.trades, "orders": self.orders, "messages": [m.to_dict() for m in self.bus.log],
                "analyst": self.analyst.history if self.analyst else []}

    # ------------------------------------------------------------------
    def _run_round(self, period: int, rnd: int, period_prices: list[float]) -> None:
        active = [t for t in self.traders if t.active]
        if not active:
            return
        snap = self.book.snapshot()
        all_prices = [t["price"] for t in self.trades]
        base_obs = {"period": period, "round": rnd, "n_periods": self.n_periods,
                    "rounds_per_period": self.rounds, "best_bid": snap["best_bid"], "best_ask": snap["best_ask"],
                    "recent_prices": all_prices[-10:],
                    "analyst_estimate": self.analyst.last_estimate if self.analyst else None}

        def decide(tr: Trader) -> Decision:
            obs = dict(base_obs, messages=self.bus.view_for(tr.agent_id, period))
            return tr.decide(obs)

        with ThreadPoolExecutor(max_workers=self.max_workers) as pool:
            decisions = {}
            for tr, d in zip(active, pool.map(decide, active)):
                decisions[tr.agent_id] = d
                if self.on_decision:
                    self.on_decision(period, rnd, len(decisions), len(active), tr, d)

        for aid, d in decisions.items():
            # Drop nonsense beliefs (e.g. small models emitting 0) so they can't poison the analyst's consensus.
            if d.belief is not None and not (self.cfg.price_min < d.belief <= self.cfg.price_max):
                d.meta["invalid_belief"] = d.belief
                d.belief = None
            if d.belief is not None:
                self.bus.publish(Message(aid, "beliefs", f"belief {d.belief}", period, rnd, {"belief": d.belief}))
            if d.message:
                self.bus.publish(Message(aid, "chat", d.message, period, rnd))

        order_ids = [t.agent_id for t in active]
        self.rng.shuffle(order_ids)
        for aid in order_ids:
            tr, d = self.by_id[aid], decisions[aid]
            rec = {"period": period, "round": rnd, "agent_id": aid, "kind": tr.kind, "role": tr.role,
                   "action": d.action, "raw_price": d.price, "price": None, "unit": tr.next_unit,
                   "belief": d.belief, "clipped": False, "traded": False, "reasoning": d.reasoning, **d.meta}
            if d.action == "pass" or d.price is None or not tr.active:
                self.orders.append(rec)
                continue
            price = min(max(d.price, self.cfg.price_min), self.cfg.price_max)
            if self.enforce_budget:
                unit = tr.next_unit
                if tr.role == "buyer" and price > unit:
                    price, rec["clipped"] = unit, True
                elif tr.role == "seller" and price < unit:
                    price, rec["clipped"] = unit, True
            rec["price"] = price
            result = self.book.submit(Order(aid, d.action, price))
            if result:
                buyer_id, seller_id, tprice = result
                b, s = self.by_id[buyer_id], self.by_id[seller_id]
                if not (b.active and s.active):     # stale order from a trader who has run out of units
                    self.orders.append(rec)
                    continue
                bval, scost = b.next_unit, s.next_unit
                b.on_trade(tprice); s.on_trade(tprice)
                rec["traded"] = True
                t = Trade(buyer_id, seller_id, tprice, period, rnd, len(self.trades)).to_dict()
                t.update(buyer_value=bval, seller_cost=scost, surplus=bval - scost)
                self.trades.append(t)
                period_prices.append(tprice)
                # Traders with no units left cannot keep standing orders.
                for x in (b, s):
                    if not x.active:
                        self.book.cancel(x.agent_id)
            self.orders.append(rec)

        if self.analyst:
            self.analyst.observe_round(period, rnd, [t["price"] for t in self.trades])
        if self.on_round:
            self.on_round(period, rnd, self)
