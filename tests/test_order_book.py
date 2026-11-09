from market.order_book import Order, OrderBook


def test_crossing_bid_trades_at_standing_ask_price():
    ob = OrderBook()
    assert ob.submit(Order("S1", "ask", 90)) is None
    assert ob.submit(Order("B1", "bid", 95)) == ("B1", "S1", 90)


def test_crossing_ask_trades_at_standing_bid_price():
    ob = OrderBook()
    ob.submit(Order("B1", "bid", 95))
    assert ob.submit(Order("S1", "ask", 80)) == ("B1", "S1", 95)


def test_non_crossing_orders_rest():
    ob = OrderBook(clear_after_trade=False)
    ob.submit(Order("B1", "bid", 80)); ob.submit(Order("S1", "ask", 90))
    assert ob.snapshot() == {"best_bid": 80, "best_ask": 90, "n_bids": 1, "n_asks": 1}


def test_new_order_replaces_old_one():
    ob = OrderBook(clear_after_trade=False)
    ob.submit(Order("B1", "bid", 80)); ob.submit(Order("B1", "bid", 85))
    assert len(ob.bids) == 1 and ob.best_bid().price == 85


def test_price_time_priority():
    ob = OrderBook(clear_after_trade=False)
    ob.submit(Order("S1", "ask", 90)); ob.submit(Order("S2", "ask", 90)); ob.submit(Order("S3", "ask", 95))
    assert ob.submit(Order("B1", "bid", 100)) == ("B1", "S1", 90)


def test_book_clears_after_trade_by_default():
    ob = OrderBook()
    ob.submit(Order("B2", "bid", 50)); ob.submit(Order("S1", "ask", 90))
    ob.submit(Order("B1", "bid", 95))
    assert ob.snapshot()["n_bids"] == 0 and ob.snapshot()["n_asks"] == 0
