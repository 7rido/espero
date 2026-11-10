"""Ticker bars for the stock perps, limited to what #73 allows; on made-up payloads and a made-up cells file."""
import datetime as dt
import json
import tempfile
import unittest
from pathlib import Path
from zoneinfo import ZoneInfo

from espero import tradfi as F

ET = ZoneInfo("America/New_York")


def et(day, hh, mm=0):
    y, m, d = (int(x) for x in day.split("-"))
    return int(dt.datetime(y, m, d, hh, mm, tzinfo=ET).timestamp())


CELLS = """market,ticker,kind,session,pairs,corr,median_bps,p95_bps,drift_bps,follows
NVDA,NVDA,US stock,regular,245,0.996,2.1,7.8,0.24,yes
NVDA,NVDA,US stock,pre-market,208,0.614,19.1,66.1,-0.91,no
SOXL,SOXL,leveraged ETF,regular,245,0.996,6.8,45.4,-1.01,yes
ARM,ARM,US stock,regular,245,0.991,10.2,30.2,-0.90,no
GOLD,GC=F,commodity,futures hours,739,0.990,1.9,6.9,0.17,yes
"""


def payload(times, opens=None):
    n = len(times)
    o = opens or [100.0 + i for i in range(n)]
    return {"chart": {"result": [{"timestamp": times, "indicators": {"quote": [
        {"open": o, "high": [x + 1 for x in o], "low": [x - 1 for x in o], "close": [x + 0.5 for x in o],
         "volume": [1000] * n}]}}]}}


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        self.cells = self.dir / "cells.csv"
        self.cells.write_text(CELLS)

    def tearDown(self):
        self.tmp.cleanup()


class TestAllowed(Base):
    def test_stocks_and_etfs_that_followed_in_the_regular_session_only(self):
        self.assertEqual(F.allowed(self.cells), [("NVDA", "NVDA"), ("SOXL", "SOXL")])
        self.assertEqual(F.ticker_for("SOXL", self.cells), "SOXL")
        for market in ("ARM", "GOLD", "UNKNOWN"):
            with self.assertRaises(F.NotAllowed):
                F.ticker_for(market, self.cells)

    def test_the_committed_cells_allow_the_37_markets_of_the_result(self):
        got = dict(F.allowed())
        self.assertEqual(len(got), 37)
        self.assertEqual(got["NVDA"], "NVDA")
        for left_out in ("SNXX", "AAOI", "ARM", "PURRDAT", "USAR", "GOLD", "XYZ100"):
            self.assertNotIn(left_out, got)


class TestBars(Base):
    def test_regular_session_bars_only_with_the_eastern_day(self):
        day = "2026-11-03"                                  # a Tuesday, after the clocks went back
        times = [et(day, 4), et(day, 9), et(day, 9, 30), et(day, 15, 30), et(day, 16), et("2026-11-07", 10, 30)]
        asked = []

        def fetch(ticker, rng, interval):
            asked.append((ticker, rng, interval))
            return payload(times)

        df = F.hourly("NVDA", fetch=fetch, cache_dir=self.dir, cells=self.cells)
        self.assertEqual(asked, [("NVDA", "730d", "1h")])
        self.assertEqual(list(df["ts"]), [et(day, 9, 30), et(day, 15, 30)])   # 04:00, 09:00, 16:00, a Saturday out
        self.assertEqual(list(df["day"]), [day, day])
        self.assertEqual(list(df.columns), F.COLUMNS)
        self.assertEqual(list(df["open"]), [102.0, 103.0])

    def test_daily_keeps_every_day_and_asks_for_five_years(self):
        asked = []
        times = [et("2026-11-02", 9, 30), et("2026-11-03", 9, 30)]
        df = F.daily("SOXL", fetch=lambda *a: asked.append(a) or payload(times), cache_dir=self.dir, cells=self.cells)
        self.assertEqual(asked, [("SOXL", "5y", "1d")])
        self.assertEqual(list(df["day"]), ["2026-11-02", "2026-11-03"])

    def test_a_bar_without_a_price_is_dropped_and_bars_come_in_time_order(self):
        times = [et("2026-11-03", 10, 30), et("2026-11-03", 9, 30)]
        p = payload(times)
        p["chart"]["result"][0]["indicators"]["quote"][0]["high"][0] = None
        self.assertEqual([r["ts"] for r in F.parse(p)], [et("2026-11-03", 9, 30)])
        self.assertEqual([r["ts"] for r in F.parse(payload(times))], sorted(times))

    def test_the_cache_serves_a_day_then_asks_again(self):
        calls = []
        times = [et("2026-11-03", 9, 30)]

        def fetch(*a):
            calls.append(a)
            return payload(times)

        clock = [1_000_000_000.0]
        F.hourly("NVDA", fetch=fetch, cache_dir=self.dir, now=lambda: clock[0], cells=self.cells)
        path = next(self.dir.glob("NVDA_730d_1h.json"))
        mtime = path.stat().st_mtime
        F.hourly("NVDA", fetch=fetch, cache_dir=self.dir, now=lambda: mtime + F.MAX_AGE_S, cells=self.cells)
        self.assertEqual(len(calls), 1)
        F.hourly("NVDA", fetch=fetch, cache_dir=self.dir, now=lambda: mtime + F.MAX_AGE_S + 1, cells=self.cells)
        self.assertEqual(len(calls), 2)
        self.assertEqual(json.loads(path.read_text())["chart"]["result"][0]["timestamp"], times)
        self.assertEqual(sorted(p.name for p in self.dir.iterdir()), ["NVDA_730d_1h.json", "cells.csv"])

    def test_hourly_bars_are_asked_by_dates_inside_the_window(self):
        self.assertEqual(F.chart_query("730d", "1h", 2_000_000_000.5),
                         {"period1": 2_000_000_000 - 729 * 86_400, "period2": 2_000_000_000, "interval": "1h"})
        self.assertEqual(F.chart_query("5y", "1d", 0.0), {"range": "5y", "interval": "1d"})

    def test_a_market_left_out_is_never_fetched(self):
        with self.assertRaises(F.NotAllowed):
            F.hourly("ARM", fetch=lambda *a: 1 / 0, cache_dir=self.dir, cells=self.cells)


if __name__ == "__main__":
    unittest.main()
