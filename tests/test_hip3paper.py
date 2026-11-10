"""The HIP-3 paper books on made-up 30-minute candles: bars, nights, warm-up, scorecards and the paced fetch."""
import datetime as dt
import json
import tempfile
import unittest
from pathlib import Path

from espero import hip3paper as P
from espero import levetf as lv


def candles(first, last, price=lambda t: 100.0):
    """A 30-minute candle every half hour from `first` to `last` (unix s), flat at price(t), 0.1 either side."""
    out = []
    for t in range(first, last, 1800):
        p = price(t)
        out.append({"t": t * 1000, "o": str(p), "h": str(p + 0.1), "l": str(p - 0.1), "c": str(p)})
    return out


TUE, WED = dt.date(2026, 11, 10), dt.date(2026, 11, 11)
EARLY = dt.date(2026, 11, 27)                                           # the day after Thanksgiving: 13:00


class TestBars(unittest.TestCase):
    def test_a_full_session_is_seven_bars_from_09_30_the_last_half_an_hour(self):
        cs = candles(lv.at(TUE, 0, 0), lv.at(WED, 0, 0), price=lambda t: 100 + (t % 7200) / 3600)
        df = P.bars(cs, "2026-11-10", lv.at(WED, 0, 0))
        self.assertEqual(len(df), 7)
        self.assertEqual(int(df["ts"].iloc[0]), lv.at(TUE, 9, 30))
        self.assertEqual(int(df["ts"].iloc[-1]), lv.at(TUE, 15, 30))
        first = [c for c in cs if lv.at(TUE, 9, 30) <= int(c["t"]) // 1000 < lv.at(TUE, 10, 30)]
        self.assertAlmostEqual(df["open"].iloc[0], float(first[0]["o"]))
        self.assertAlmostEqual(df["close"].iloc[0], float(first[-1]["c"]))
        self.assertAlmostEqual(df["high"].iloc[0], max(float(c["h"]) for c in first))
        self.assertEqual(set(df["day"]), {"2026-11-10"})
        last = [c for c in cs if int(c["t"]) // 1000 == lv.at(TUE, 15, 30)][0]
        self.assertAlmostEqual(df["close"].iloc[-1], float(last["c"]))       # the 16:00 candle is after the close

    def test_only_ended_bars_a_missing_candle_and_an_early_close(self):
        cs = candles(lv.at(TUE, 0, 0), lv.at(WED, 0, 0))
        self.assertEqual(len(P.bars(cs, "2026-11-10", lv.at(TUE, 11, 0))), 1)        # 10:30's bar not ended
        holey = [c for c in cs if int(c["t"]) // 1000 != lv.at(TUE, 10, 0)]
        self.assertEqual(len(P.bars(holey, "2026-11-10", lv.at(WED, 0, 0))), 6)       # the 09:30 bar is incomplete
        ce = candles(lv.at(EARLY, 0, 0), lv.at(EARLY, 23, 0))
        de = P.bars(ce, "2026-11-27", lv.at(EARLY, 23, 0))
        self.assertEqual([dt.datetime.fromtimestamp(t, lv.ET).strftime("%H:%M") for t in de["ts"]],
                         ["09:30", "10:30", "11:30", "12:30"])
        sat = dt.date(2026, 11, 14)
        self.assertTrue(P.bars(candles(lv.at(sat, 0, 0), lv.at(sat, 23, 0)), "2026-11-14", lv.at(sat, 23, 0)).empty)


class TestNights(unittest.TestCase):
    def test_close_to_next_open_and_a_night_still_open(self):
        price = lambda t: 101.0 if t >= lv.at(WED, 9, 0) else 100.0           # noqa: E731
        cs = candles(lv.at(TUE, 0, 0), lv.at(WED, 12, 0), price)
        got = P.book76(cs, "2026-11-10", lv.at(WED, 12, 0))
        self.assertEqual([x["day"] for x in got], ["2026-11-10"])      # Wednesday's close has not come yet
        n = got[0]
        self.assertEqual((n["buy"], n["sell"], n["open"]), (100.0, 101.0, False))
        self.assertAlmostEqual(n["hours"], 17.5)
        self.assertAlmostEqual(n["net"], 0.01 - 28e-4 - 0.10 * 17.5 / 8760)
        cs2 = candles(lv.at(TUE, 0, 0), lv.at(WED, 3, 0))
        open_ = P.book76(cs2, "2026-11-10", lv.at(WED, 3, 0))
        self.assertEqual(len(open_), 1)
        self.assertTrue(open_[0]["open"])
        self.assertAlmostEqual(open_[0]["hours"], 11.0)

    def test_an_early_close_buys_at_13_00(self):
        mon = dt.date(2026, 11, 30)
        price = lambda t: 50.0 if t < lv.at(EARLY, 13, 30) else 60.0           # noqa: E731
        got = P.book76(candles(lv.at(EARLY, 0, 0), lv.at(mon, 12, 0), price), "2026-11-27", lv.at(mon, 12, 0))
        self.assertEqual((got[0]["buy"], got[0]["sell"]), (50.0, 60.0))
        self.assertAlmostEqual(got[0]["hours"], 68.5)                           # Friday 13:00 to Monday 09:30

    def test_a_friday_is_held_to_monday(self):
        fri, mon = dt.date(2026, 11, 13), dt.date(2026, 11, 16)
        cs = candles(lv.at(fri, 0, 0), lv.at(mon, 12, 0))
        got = P.book76(cs, "2026-11-13", lv.at(mon, 12, 0))
        self.assertAlmostEqual(got[0]["hours"], 65.5)
        self.assertFalse(got[0]["open"])


class TestBook(unittest.TestCase):
    def test_warm_up_and_open_trades_are_left_out_of_the_scorecard(self):
        cs = candles(lv.at(TUE, 0, 0), lv.at(WED, 12, 0))
        book = P.build({"AAA": cs}, lv.at(WED, 12, 0))
        late = P.build({"AAA": candles(lv.at(TUE, 0, 0), lv.at(WED, 3, 0))}, lv.at(WED, 3, 0))
        self.assertEqual((late["76"]["score"]["n"], len(late["76"]["nights"])), (0, 1))   # an open night is not scored
        self.assertEqual(book["start"], P.START)
        self.assertEqual(book["76"]["score"]["n"], 1)
        self.assertAlmostEqual(book["76"]["score"]["mean"], (0.0 - 28e-4 - 0.10 * 17.5 / 8760) * 1e4)
        rows = [{"r": 1.0, "open": False, "warmup": True}, {"r": -1.0, "open": True, "warmup": False},
                {"r": 2.0, "open": False, "warmup": False}]
        self.assertEqual([x["r"] for x in rows if not x["open"] and not x["warmup"]], [2.0])
        self.assertEqual(P.scorecard([2.0, -1.0])["pf"], 2.0)
        self.assertIn("Both failed their backtests", P.render(book))
        self.assertIn("no paper run yet", P.render(None))

    def test_written_whole_and_read_back(self):
        with tempfile.TemporaryDirectory() as d:
            self.assertIsNone(P.read(Path(d)))
            P.write(Path(d), {"at": 1, "x": [1.5]})
            self.assertEqual(P.read(Path(d))["x"], [1.5])
            self.assertEqual([p.name for p in Path(d).iterdir()], [P.OUT])


class TestRefresh(unittest.TestCase):
    def test_asks_only_what_the_cache_lacks_paced_and_out_of_the_sweep(self):
        asked, slept = [], []
        now = lv.at(WED, 12, 0)
        hour = 1_794_000_000 - 1_794_000_000 % 3600
        clock = iter([hour + 60 * 20] + [hour + 60 * 30] * 10)

        def post(body):
            asked.append(body)
            r = body["req"]
            return candles(r["startTime"] // 1000, min(r["endTime"] // 1000, r["startTime"] // 1000 + 7200))

        with tempfile.TemporaryDirectory() as d:
            got = P.refresh(Path(d), ["AAA", "BBB"], now, post=post, sleep=slept.append, clock=lambda: next(clock))
            self.assertEqual([b["req"]["coin"] for b in asked], ["xyz:AAA", "xyz:BBB"])
            self.assertEqual(asked[0]["req"]["interval"], "30m")
            first_ms = int(dt.datetime(2026, 10, 29, tzinfo=dt.timezone.utc).timestamp() * 1000)
            self.assertEqual(asked[0]["req"]["startTime"], first_ms)
            self.assertEqual(slept, [20, P.PAUSE_S])                   # minute 20 waits; then one pause between two
            self.assertEqual(len(got["AAA"]), 4)
            asked.clear()
            P.refresh(Path(d), ["AAA"], now, post=post, sleep=lambda s: None, clock=lambda: 0)
            self.assertEqual(asked[0]["req"]["startTime"], first_ms + 3 * 1_800_000)   # from the last candle again
            self.assertEqual(len(json.loads((Path(d) / "AAA.json").read_text())), 7)
            P.refresh(Path(d), ["AAA"], now, post=lambda b: 1 / 0, sleep=lambda s: None, clock=lambda: 0)
            self.assertEqual(len(P.cached(Path(d), "AAA")), 7)          # an error keeps the cache


if __name__ == "__main__":
    unittest.main()
