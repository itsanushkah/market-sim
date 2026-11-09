from market.config import MarketConfig, TraderSpec, load_market
from market.equilibrium import compute_equilibrium


def test_symmetric_market_has_known_equilibrium():
    e = compute_equilibrium(load_market("market/configs/symmetric.yaml"))
    assert e.quantity == 11
    assert e.price_low == e.price_high == 100
    assert e.max_surplus == 600   # 1390 - 790


def test_price_interval_when_not_unique():
    cfg = MarketConfig("t", [TraderSpec("B", "buyer", [100, 50]), TraderSpec("S", "seller", [20, 80])])
    e = compute_equilibrium(cfg)
    assert e.quantity == 1
    # 1 unit trades at any p in [max(20, 50), min(100, 80)] = [50, 80]
    assert (e.price_low, e.price_high) == (50, 80)
    assert e.max_surplus == 80


def test_no_trade_market():
    cfg = MarketConfig("t", [TraderSpec("B", "buyer", [10]), TraderSpec("S", "seller", [50])])
    assert compute_equilibrium(cfg).quantity == 0


def test_shock_shifts_equilibrium_price():
    cfg = load_market("market/configs/shock.yaml")
    assert compute_equilibrium(cfg.for_period(0)).price_mid == 100
    assert compute_equilibrium(cfg.for_period(2)).price_mid == 130
