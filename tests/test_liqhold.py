import io
import tempfile
import unittest
import zipfile
from pathlib import Path

import numpy as np
import pandas as pd

from espero import fundsplit
from espero import liqhold as lh
from tests.approx import approx

DAY = 86_400
T0 = int(pd.Timestamp("2026-11-02", tz="UTC").timestamp())


def bars(n_days=4, start=T0 - DAY, step=0.0):
    ts = np.arange(start, start + n_days * DAY, 300)
    px = 100 * np.exp(step * np.arange(len(ts)))
    return pd.DataFrame({"open": px, "close": px}, index=pd.Index(ts))


def ledger(rows):
    return pd.DataFrame(rows, columns=["ts", "direction", "group", "coin", "day"])


def _tr(net_first, net_second, coins=("BTC", "ETH", "ADA"), n=40, measured_sign=1.0):
    rows = []
    days1 = pd.date_range("2026-11-01", periods=n, freq="D").strftime("%Y-%m-%d")
    days2 = pd.date_range("2027-01-05", periods=n, freq="D").strftime("%Y-%m-%d")
    rng = np.random.default_rng(0)
    for h in lh.HORIZONS:
        for c in coins:
            sign = measured_sign if c in lh.MEASURED else 1.0
            for d in days1:
                rows.append({"h": h, "coin": c, "day": d, "net": sign * net_first + rng.normal(0, 1e-4),
                             "measured": c in lh.MEASURED})
            for d in days2:
                rows.append({"h": h, "coin": c, "day": d, "net": sign * net_second + rng.normal(0, 1e-4),
                             "measured": c in lh.MEASURED})
    return pd.DataFrame(rows)


class TestLiqhold(unittest.TestCase):
    """#45: the held down-breaks' trades, criteria and the funding archive's scaling."""

    def test_round_trip_measured_or_assumed(self):
        assert lh.round_trip("BTC") == approx(9.91e-4, abs=1e-6)
        assert lh.round_trip("HBAR") == lh.ASSUMED_RT

    def test_events_keep_forced_down_breaks_in_the_window(self):
        led = ledger([(T0, -1, "forced", "BTC", "2026-11-02"), (T0, 1, "forced", "BTC", "2026-11-02"),
                      (T0, -1, "organic", "BTC", "2026-11-02"), (T0, -1, "forced", "BTC", "2026-10-29"),
                      (T0, -1, "forced", "BTC", "2027-04-01")])
        assert len(lh.events(led)) == 1

    def test_trades_enter_at_ts_and_charge_cost_and_funding(self):
        b = bars(step=1e-5)
        b.loc[T0 + 300:, ["open", "close"]] *= 1.02          # a jump one bar after entry: entering at ts catches it
        f = pd.DataFrame({"ts": [T0 + 8 * 3600], "rate": [0.0002]})
        led = ledger([(T0, -1, "forced", "BTC", "2026-11-02")])
        tr = lh.trades(led, {"BTC": b}, {"BTC": f})
        assert set(tr["h"]) == {"4h", "12h", "1d"}
        r4 = tr[tr["h"] == "4h"].iloc[0]
        i = b.index.get_loc(T0)
        assert r4["gross"] == approx(b["close"].iloc[i + 47] / b["open"].iloc[i] - 1)   # entry at ts itself
        assert r4["funding"] == 0.0                                                           # 08:00 is after 4 h
        r12 = tr[tr["h"] == "12h"].iloc[0]
        assert r12["funding"] == approx(-0.0002)
        assert r12["net"] == approx(r12["gross"] - lh.round_trip("BTC") - 0.0002)

    def test_criteria_pass_when_everything_holds(self):
        res = lh.criteria(_tr(0.002, 0.002))
        assert all(res[h]["pass"] for h in lh.HORIZONS)

    def test_criteria_halves_coins_and_measured(self):
        assert not lh.criteria(_tr(0.004, -0.0005))["4h"]["halves"]
        res = lh.criteria(_tr(0.002, 0.002, measured_sign=-1.0))
        assert not res["4h"]["measured"] and not res["4h"]["pass"]
        assert not res["4h"]["coins"]                              # 2 of 3 coins negative

    def test_criteria_measured_coins_must_pay_too(self):
        res = lh.criteria(_tr(0.002, 0.002, coins=("BTC", "ADA", "AVAX", "BNB"), measured_sign=-1.0))
        assert res["4h"]["coins"] and res["4h"]["pays"] and not res["4h"]["measured"]
        assert not res["4h"]["pass"]

    def test_criteria_holm_needs_significance(self):
        noisy = _tr(0.0, 0.0)
        noisy["net"] = np.random.default_rng(3).normal(0, 0.01, len(noisy))
        res = lh.criteria(noisy)
        assert not any(res[h]["pays"] for h in lh.HORIZONS)

    def test_run_without_a_ledger(self):
        with tempfile.TemporaryDirectory() as d:
            tmp_path = Path(d)
            out = lh.run(tmp_path, bars_data=tmp_path, funding_data=tmp_path, get=lambda url: None)
        assert "no forced down-break" in out["note"] and out["equity"] is None

    def test_unscaled_funding_keeps_the_settled_rate(self):
        csv = "calc_time,funding_interval_hours,last_funding_rate\n1793404800000,4,0.0001\n"
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as z:
            z.writestr("x.csv", csv)
        assert fundsplit.parse(buf.getvalue())["rate"].iloc[0] == approx(0.0002)      # #32's scaling
        assert fundsplit.parse(buf.getvalue(), scaled=False)["rate"].iloc[0] == approx(0.0001)


if __name__ == "__main__":
    unittest.main()
