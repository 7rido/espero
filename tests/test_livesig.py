"""#71's streaming engine on synthetic trades only: it emits exactly what the batch functions find on the same bars."""
import datetime as dt
import tempfile
import unittest
from pathlib import Path

import numpy as np
import pandas as pd

from espero import levetf as lv
from espero import livesig as L

try:
    import zstandard  # noqa: F401
    HAVE_ZSTD = True
except ImportError:
    HAVE_ZSTD = False

T0 = int(dt.datetime(2026, 11, 10, tzinfo=dt.timezone.utc).timestamp())


def rec(coin, t_ms, px, q, rt=None):
    sym = f"{coin}USDT"
    return {"rt": rt if rt is not None else t_ms + 50, "ch": "trade", "s": sym,
            "d": {"stream": sym.lower() + "@trade", "data": {"e": "trade", "T": t_ms, "s": sym, "p": str(px),
                                                             "q": str(q), "m": False}}}


def crash_bars(n=120, crash_at=100, start=T0):
    """A quiet walk, then one bar that falls through the 4-hour low on heavy volume: lows' trigger."""
    rng = np.random.default_rng(4)
    close = 100 + np.cumsum(rng.normal(0, 0.05, n))
    close[crash_at:] = close[crash_at - 1] * 0.95
    openp = np.r_[close[0], close[:-1]]
    high = np.maximum(openp, close) + 0.02
    low = np.minimum(openp, close) - 0.02
    vol = rng.uniform(1.0, 2.0, n)
    vol[crash_at] = 60.0
    ts = start + np.arange(n) * L.BAR_S
    return pd.DataFrame({"open": openp, "high": high, "low": low, "close": close, "volume": vol},
                        index=pd.Index(ts, name="ts"))


def trades_of(bars, coin):
    """Four prints a bar: open, high, low, close, each a quarter of the volume, in time order."""
    out = []
    for ts, r in bars.iterrows():
        base = int(ts) * 1000
        for k, px in enumerate((r["open"], r["high"], r["low"], r["close"])):
            out.append(rec(coin, base + 10_000 + 60_000 * k, px, r["volume"] / 4))
    return out


def run(records, coins=("BTC",)):
    eng = L.Engine(coins)
    out = []
    for r in records:
        out += eng.feed(r)
    return eng, out


class TestBars(unittest.TestCase):
    def test_a_trade_record_is_read_and_others_are_not(self):
        self.assertEqual(L.trade_of(rec("BTC", 1_000, 100.5, 0.25)), ("BTC", 1_000, 100.5, 0.25))
        self.assertIsNone(L.trade_of({"rt": 1, "ch": "depth20@100ms", "d": {}}))
        self.assertIsNone(L.trade_of(rec("PEPE", 1_000, 1.0, 1.0)))
        self.assertIsNone(L.trade_of(rec("BTC", 1_000, 0.0, 0.0)))            # the stream's "X": "NA" records
        self.assertIsNone(L.trade_of(rec("BTC", 1_000, 100.0, 0.0)))

    def test_ohlc_and_base_volume_by_trade_time(self):
        b = L.Bars(("BTC",))
        for t, px, q in ((T0 * 1000 + 1, 100.0, 1.0), (T0 * 1000 + 2, 101.0, 2.0), (T0 * 1000 + 3, 99.0, 0.5),
                         (T0 * 1000 + 299_999, 100.5, 0.5)):
            b.add("BTC", t, px, q)
        self.assertEqual(b.close((T0 + 300) * 1000 + 1_999), [])                 # inside the grace
        self.assertEqual(b.close((T0 + 300) * 1000 + 2_000), [T0])
        f = b.frame("BTC")
        self.assertEqual(f.loc[T0].tolist(), [100.0, 101.0, 99.0, 100.5, 4.0])

    def test_an_empty_bar_carries_the_last_close_and_a_late_trade_is_counted(self):
        b = L.Bars(("BTC",))
        b.add("BTC", T0 * 1000 + 5, 100.0, 1.0)
        b.close((T0 + 900) * 1000 + 2_000)
        self.assertEqual(b.frame("BTC").loc[T0 + 600].tolist(), [100.0, 100.0, 100.0, 100.0, 0.0])
        b.add("BTC", T0 * 1000 + 6, 50.0, 1.0)
        self.assertEqual(b.late["BTC"], 1)
        self.assertEqual(b.frame("BTC").loc[T0, "close"], 100.0)


class TestIdentity(unittest.TestCase):
    def test_the_engine_emits_lows_events_exactly(self):
        bars = crash_bars()
        want = [e.key for e in L.events_24(bars, "BTC")]
        self.assertTrue(want)                                                    # the synthetic crash triggers
        eng, out = run(trades_of(bars, "BTC") + [{"rt": (int(bars.index[-1]) + 600) * 1000}])
        self.assertEqual(sorted(e.key for e in out if e.rule == "24"), sorted(want))
        pd.testing.assert_frame_equal(eng.bars.frame("BTC"), bars, check_dtype=False, check_names=False)

    def test_the_engine_emits_bids_events_exactly(self):
        bars = crash_bars()
        want = sorted(e.key for e in L.events_31(bars, "BTC"))
        self.assertTrue(want)
        _, out = run(trades_of(bars, "BTC") + [{"rt": (int(bars.index[-1]) + 600) * 1000}])
        self.assertEqual(sorted(e.key for e in out if e.rule == "31"), want)

    def test_an_event_is_emitted_when_its_bar_closes_and_never_again(self):
        bars = crash_bars()
        _, out = run(trades_of(bars, "BTC") + [{"rt": (int(bars.index[-1]) + 3_600) * 1000}] * 3)
        e = [x for x in out if x.rule == "24"][0]
        self.assertGreaterEqual(e.emitted_ms, e.ts * 1000 + L.CLOSE_GRACE_MS)
        self.assertLess(e.emitted_ms, e.ts * 1000 + 300_000)
        self.assertEqual(len([x for x in out if x.rule == "24"]), len(set(x.key for x in out if x.rule == "24")))

    def test_no_return_reaches_an_event(self):
        bars = crash_bars()
        _, out = run(trades_of(bars, "BTC") + [{"rt": (int(bars.index[-1]) + 600) * 1000}])
        self.assertTrue(all(set(vars(e)) == {"rule", "coin", "side", "ts", "emitted_ms"} for e in out))


class TestTheCloseRules(unittest.TestCase):
    def day_bars(self, coin_up=True):
        d = dt.date(2026, 11, 10)                                                # a Tuesday, a full session
        start, end = lv.at(dt.date(2026, 11, 9), 15, 0), lv.at(d, 16, 30)
        ts = np.arange(start, end, L.BAR_S)
        px = np.linspace(100.0, 103.0 if coin_up else 97.0, len(ts))
        return d, pd.DataFrame({"open": px, "high": px + 0.01, "low": px - 0.01, "close": px,
                                "volume": np.ones(len(ts))}, index=pd.Index(ts, name="ts"))

    def test_29_trades_against_the_days_move_and_34_with_it(self):
        d, up = self.day_bars(True)
        self.assertEqual([(e.rule, e.side, e.ts) for e in L.events_close(up, "BTC", d, "29")],
                         [("29", "sell", lv.at(d, 16, 0))])
        self.assertEqual([(e.rule, e.side, e.ts) for e in L.events_close(up, "SOL", d, "34")],
                         [("34", "buy", lv.at(d, 15, 45))])
        _, down = self.day_bars(False)
        self.assertEqual(L.events_close(down, "BTC", d, "29")[0].side, "buy")

    def test_the_engine_emits_them_when_the_deciding_bar_closes(self):
        d, up = self.day_bars(True)
        records = trades_of(up, "BTC") + trades_of(up, "SOL")
        records.sort(key=lambda r: r["rt"])
        _, out = run(records, coins=("BTC", "SOL"))
        e29 = [e for e in out if e.rule == "29"]
        self.assertEqual([(e.coin, e.side) for e in e29], [("BTC", "sell")])
        self.assertLess(e29[0].emitted_ms - lv.at(d, 16, 0) * 1000, 300_000)
        self.assertEqual([(e.coin, e.side) for e in out if e.rule == "34"], [("SOL", "buy")])

    def test_no_signal_on_an_early_close(self):
        self.assertIsNone(L.signal_bar("29", dt.date(2026, 11, 27)))
        self.assertEqual(L.signal_bar("34", dt.date(2026, 11, 10)), lv.at(dt.date(2026, 11, 10), 15, 45) - 300)


class TestComparison(unittest.TestCase):
    def ev(self, rule="24", coin="BTC", ts=1, side="buy"):
        return L.Event(rule, coin, side, ts)

    def test_agreement_over_the_union(self):
        r = L.compare([self.ev(ts=1), self.ev(ts=2)], [self.ev(ts=2), self.ev(ts=3)])
        self.assertEqual((r["matched"], r["union"]), (1, 3))
        self.assertAlmostEqual(r["agreement"], 1 / 3)
        self.assertEqual(L.compare([], [])["agreement"], 1.0)

    def test_a_day_agrees_at_95_percent_and_misses_are_classed(self):
        live = [self.ev(ts=t) for t in range(1, 21)] + [self.ev(ts=99)]
        batch = [self.ev(ts=t) for t in range(1, 21)] + [self.ev(ts=98)]
        closed = [self.ev(ts=t) for t in range(1, 21)] + [self.ev(ts=99)]           # the tape had 99, not 98
        r = L.day_reading(live, batch, closed)
        self.assertFalse(r["agrees"])                                                  # 20 of 22
        self.assertEqual(sorted(r["input"]), sorted([self.ev(ts=99).key, self.ev(ts=98).key]))
        self.assertEqual(r["streaming"], [])
        r2 = L.day_reading([self.ev(ts=t) for t in range(1, 21)], [self.ev(ts=t) for t in range(1, 22)],
                           [self.ev(ts=t) for t in range(1, 22)])
        self.assertTrue(r2["agrees"])                                                  # 20 of 21
        self.assertEqual(r2["streaming"], [self.ev(ts=21).key])

    def test_the_reading_needs_thirty_days_and_ninety_percent(self):
        yes, no = {"agrees": True}, {"agrees": False}
        self.assertFalse(L.reading([yes] * 29)["reproduces"])
        self.assertTrue(L.reading([yes] * 27 + [no] * 3)["reproduces"])
        self.assertFalse(L.reading([yes] * 26 + [no] * 4)["reproduces"])

    def test_latency_per_rule(self):
        evs = [L.Event("24", "BTC", "buy", 100, 102_000), L.Event("24", "ETH", "buy", 100, 104_000),
               L.Event("24", "SOL", "buy", 100, 130_000)]
        got = L.latency_ms(evs)["24"]
        self.assertEqual(got[0], 4_000.0)                                         # the median, not the mean
        self.assertAlmostEqual(got[1], 27_400.0)

    def test_events_are_appended_with_one_header(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / L.EVENTS
            L.append_events(p, [L.Event("24", "BTC", "buy", 1, 2)])
            L.append_events(p, [L.Event("31", "ETH", "buy", 3, 4)])
            self.assertEqual(p.read_text().splitlines(), ["rule,coin,side,ts,emitted_ms", "24,BTC,buy,1,2",
                                                          "31,ETH,buy,3,4"])

    def test_warm_days_reach_back_to_the_previous_session(self):
        self.assertEqual(L.warm_days("2026-11-10"), ["2026-11-09"])
        self.assertEqual(L.warm_days("2026-11-09"), ["2026-11-06", "2026-11-07", "2026-11-08"])   # a Monday
        self.assertIs(L.rule(), L.day_reading)


@unittest.skipUnless(HAVE_ZSTD, "needs zstandard")
class TestReplayFromTape(unittest.TestCase):
    def test_a_recorded_day_replays_to_the_batch_events(self):
        from espero import rawrec

        bars = crash_bars(start=T0)
        with tempfile.TemporaryDirectory() as d:
            raw = Path(d)
            w = rawrec.HourWriter(raw, "binance")
            import json
            for r in trades_of(bars, "BTC"):
                w.write(rawrec.line(r["rt"], "trade", r["s"], json.dumps(r["d"]).encode()), r["rt"])
            w.close()
            live, late = L.replay(raw, "2026-11-10", warm={})
            self.assertEqual(sum(late.values()), 0)
            want = [e for e in L.day_events({"BTC": bars}, "2026-11-10") if e.rule in ("24", "31")]
            self.assertEqual(sorted(e.key for e in live), sorted(e.key for e in want))
            closed = L.tape_bars(raw, ["2026-11-10"])["BTC"]
            pd.testing.assert_frame_equal(closed, bars, check_dtype=False, check_names=False)


if __name__ == "__main__":
    unittest.main()
