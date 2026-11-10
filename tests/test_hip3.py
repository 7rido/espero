"""Hyperliquid's builder-deployed perps: fees, the liquidity screen and the ticker map, on made-up payloads only."""
import json
import tempfile
import unittest
from pathlib import Path

from espero import hip3 as H

DAY = H.DAY_MS
NOW = 20_000 * DAY + 5 * 3_600_000            # five hours into a UTC day


def payload(*rows):
    """(name, mark, prev, funding, oi, volume, extra universe fields, impactPxs)"""
    meta = {"universe": [dict({"name": r[0], "maxLeverage": 10, "deployerFeeScale": "1.0"}, **r[6]) for r in rows]}
    ctxs = [{"markPx": str(r[1]), "prevDayPx": str(r[2]), "funding": str(r[3]), "openInterest": str(r[4]),
             "dayNtlVlm": str(r[5]), "impactPxs": r[7]} for r in rows]
    return [meta, ctxs]


def market(coin, volume):
    return H.Market(coin, 100.0, 0.0, 0.0, 1e6, volume, 10, 0.9, 0.3, True, 1.0)


def days(n, usd, last_ms=NOW):
    """`n` complete days of `usd` each at a close of 50, then the day still forming with a huge volume."""
    start = last_ms // DAY * DAY
    return [{"t": start - k * DAY, "v": str(usd / 50), "c": "50"} for k in range(n, 0, -1)] + \
           [{"t": start, "v": "1e12", "c": "50"}]


class TestFees(unittest.TestCase):
    def test_twice_the_venues_fee_and_a_tenth_of_that_in_growth_mode(self):
        self.assertEqual(H.fees_bps(1.0, growth=False), (9.0, 3.0))
        taker, maker = H.fees_bps(1.0, growth=True)
        self.assertAlmostEqual(taker, 0.9)
        self.assertAlmostEqual(maker, 0.3)

    def test_the_scale_below_and_above_a_full_share(self):
        self.assertAlmostEqual(H.fee_scale(0.0), 1.0)
        self.assertAlmostEqual(H.fee_scale(0.5), 1.5)
        self.assertAlmostEqual(H.fee_scale(1.0), 2.0)
        self.assertAlmostEqual(H.fee_scale(3.0), 6.0)


class TestParse(unittest.TestCase):
    def test_a_market_in_dollars_with_its_fees_and_delisted_ones_dropped(self):
        got = H.parse(payload(
            ("xyz:NVDA", 180.0, 150.0, 1e-5, 1000, 7e8, {"growthMode": "enabled", "maxLeverage": 20},
             ["179.99", "180.08"]),
            ("xyz:GOLD", 4000.0, 4000.0, 0.0, 10, 5e7, {}, None),
            ("xyz:OLD", 1.0, 1.0, 0.0, 1, 1.0, {"isDelisted": True}, None),
            ("xyz:BAD", "x", 1.0, 0.0, 1, 1.0, {}, None)))
        self.assertEqual([m.coin for m in got], ["xyz:NVDA", "xyz:GOLD"])
        n, g = got
        self.assertEqual((n.name, n.max_leverage, n.growth), ("NVDA", 20, True))
        self.assertAlmostEqual(n.change, 0.2)
        self.assertAlmostEqual(n.oi_usd, 180_000.0)
        self.assertAlmostEqual(n.taker_bps, 0.9)
        self.assertAlmostEqual(n.impact_bps, (180.08 / 179.99 - 1) * 1e4)
        self.assertEqual((g.growth, g.taker_bps, g.maker_bps, g.impact_bps, g.change), (False, 9.0, 3.0, None, 0.0))

    def test_one_request_names_the_exchange(self):
        asked = []
        H.markets(post=lambda body: asked.append(body) or payload())
        self.assertEqual(asked, [{"type": "metaAndAssetCtxs", "dex": "xyz"}])


class TestScreen(unittest.TestCase):
    def test_the_median_of_the_last_thirty_complete_days(self):
        self.assertIsNone(H.median_day_usd(days(29, 6e6), NOW))            # the forming day does not make thirty
        self.assertAlmostEqual(H.median_day_usd(days(30, 6e6), NOW), 6e6)
        old = [{"t": NOW // DAY * DAY - (31 + k) * DAY, "v": "1e9", "c": "50"} for k in range(40)]
        self.assertAlmostEqual(H.median_day_usd(old + days(30, 6e6), NOW), 6e6)   # only the last thirty count
        mixed = days(30, 6e6)
        for c in mixed[:14]:
            c["v"] = "0"
        self.assertAlmostEqual(H.median_day_usd(mixed, NOW), 6e6)          # a median: fourteen empty days leave it

    def test_only_markets_already_at_the_bar_are_asked_and_each_request_is_paced(self):
        asked, slept = [], []

        def candles_of(coin):
            asked.append(coin)
            return days(30, {"xyz:A": 9e6, "xyz:B": 5e6, "xyz:C": 4.9e6}[coin])

        rows = [market("xyz:C", 6e6), market("xyz:A", 8e6), market("xyz:D", 4.9e6), market("xyz:B", 5e6)]
        got = H.screen(rows, candles_of, NOW, sleep=slept.append)
        self.assertEqual(asked, ["xyz:A", "xyz:C", "xyz:B"])                # most traded first; D never asked
        self.assertEqual({r["coin"]: r["passes"] for r in got}, {"xyz:A": True, "xyz:C": False, "xyz:B": True})
        self.assertEqual(slept, [H.PAUSE_S, H.PAUSE_S])                     # between requests, not after the last

    def test_a_young_market_does_not_pass(self):
        got = H.screen([market("xyz:NEW", 9e9)], lambda coin: days(12, 9e9), NOW, sleep=lambda s: None)
        self.assertEqual((got[0]["median_day_usd"], got[0]["passes"]), (None, False))

    def test_the_screen_is_kept_whole_and_read_back(self):
        with tempfile.TemporaryDirectory() as d:
            self.assertIsNone(H.read_screen(Path(d)))
            path = H.write_screen(Path(d), [{"coin": "xyz:A", "passes": True}], NOW)
            self.assertEqual(json.loads(path.read_text())["min_day_usd"], H.MIN_DAY_USD)
            self.assertEqual(H.read_screen(Path(d))["rows"][0]["coin"], "xyz:A")
            self.assertEqual([p.name for p in Path(d).iterdir()], [H.SCREEN])

    def test_the_days_asked_for_cover_the_screen(self):
        asked = []
        H.daily_candles("xyz:A", NOW, post=lambda body: asked.append(body) or [])
        req = asked[0]["req"]
        self.assertEqual(asked[0]["type"], "candleSnapshot")
        self.assertEqual((req["coin"], req["interval"], req["endTime"]), ("xyz:A", "1d", NOW))
        self.assertGreaterEqual(NOW - req["startTime"], (H.SCREEN_DAYS + 1) * DAY)


class TestTheMap(unittest.TestCase):
    def test_the_committed_map_names_each_market_once_with_a_known_kind(self):
        with H.MAP.open(encoding="utf-8") as fh:
            names = [line.split(",")[0] for line in fh.read().splitlines()[1:]]
        eq = H.ticker_map()
        self.assertEqual(len(names), len(set(names)))
        self.assertEqual(len(eq), len(names))
        for name, e in eq.items():
            self.assertIn(e.kind, H.KINDS, name)
            self.assertEqual(bool(e.ticker), e.kind != "no listed equivalent", name)
            self.assertEqual(bool(e.ticker), bool(e.since), name)
        self.assertEqual((eq["NVDA"].ticker, eq["XYZ100"].ticker, eq["CRCL"].since), ("NVDA", "NQ=F", "2025-06-05"))

    def test_years_of_history(self):
        self.assertAlmostEqual(H.Equivalent("X", "US stock", "2021-11-09").years("2026-11-09"), 5.0, places=1)
        self.assertIsNone(H.Equivalent("", "no listed equivalent", "").years("2026-11-09"))


class TestRender(unittest.TestCase):
    def test_the_table_says_what_passed_and_what_was_never_screened(self):
        rows = [market("xyz:NVDA", 7e8), market("xyz:TINY", 1e5), market("xyz:NEWCO", 6e6)]
        eq = {"NVDA": H.Equivalent("NVDA", "US stock", "1999-01-22")}
        plain = H.render(rows, eq, None, "2026-11-09")
        self.assertIn("3 live markets, 2 with $5.0M or more in the last 24 hours.", plain)
        self.assertIn("espero hip3 --screen", plain)
        self.assertNotIn("TINY", plain)
        self.assertIn("not mapped", plain)
        self.assertIn("27.8 y", plain)
        scr = {"rows": [{"coin": "xyz:NVDA", "median_day_usd": 1.03e8, "passes": True},
                        {"coin": "xyz:NEWCO", "median_day_usd": None, "passes": False}]}
        seen = H.render(rows, eq, scr, "2026-11-09")
        self.assertIn("1 of them above that on the 30-day median too.", seen)
        self.assertIn("$103.0M", seen)


if __name__ == "__main__":
    unittest.main()
