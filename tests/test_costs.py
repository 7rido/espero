import pytest

from espero import costs


@pytest.fixture
def table(monkeypatch):
    t = {("hyperliquid", "BTC", "taker", 0, "all", "all"): 0.4,
         ("hyperliquid", "BTC", "taker", 0, "funding", "settlement"): 1.1,
         ("hyperliquid", "BTC", "maker_cons", 60, "all", "all"): -3.0}
    monkeypatch.setattr(costs, "TABLE", t)
    return t


def test_taker_leg_is_fee_plus_half_spread(table):
    assert costs.leg("hyperliquid", "BTC", "taker") == pytest.approx(4.9)
    assert costs.leg("hyperliquid", "BTC", "taker", ("funding", "settlement")) == pytest.approx(5.6)


def test_maker_leg_adds_adverse_selection_only_when_asked(table):
    assert costs.leg("hyperliquid", "BTC", "maker") == pytest.approx(1.5)
    assert costs.leg("hyperliquid", "BTC", "maker", adverse=True) == pytest.approx(4.5)


def test_round_trip(table):
    assert costs.round_trip("hyperliquid", "BTC", "maker", "taker") == pytest.approx(6.4)


def test_unmeasured_raises(table):
    with pytest.raises(costs.NotMeasured):
        costs.leg("hyperliquid", "DOGE", "taker")
    with pytest.raises(costs.NotMeasured):
        costs.leg("binance", "BTC", "taker")
    with pytest.raises(ValueError):
        costs.leg("hyperliquid", "BTC", "stop")
