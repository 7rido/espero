"""What the tabbed home screen shows (espero/screen_data.py), on made-up data only."""
import json
import math
import tempfile
import time
import unittest
from pathlib import Path

import numpy as np
import pandas as pd

from espero import approvals
from espero import screen_data as D

NOW = 1793750400.0   # Wednesday 2026-11-04 00:00 UTC


def ctx(name, mark, prev, funding="0.0000125", oi="10", vol="1e7"):
    return {"name": name}, {"markPx": str(mark), "prevDayPx": str(prev), "funding": funding, "openInterest": oi,
                            "dayNtlVlm": vol}


def payload(*rows):
    return {"universe": [r[0] for r in rows]}, [r[1] for r in rows]


class TestMarket(unittest.TestCase):
    def test_contexts_read_price_move_funding_and_size(self):
        rows = D.parse_contexts(payload(ctx("BTC", 110, 100, oi="2", vol="5e9"), ctx("BAD", "x", 1)))
        self.assertEqual(len(rows), 1)
        c = rows[0]
        self.assertAlmostEqual(c.change, 0.10)
        self.assertAlmostEqual(c.oi_usd, 220.0)
        self.assertEqual(c.volume_usd, 5e9)

    def test_a_delisted_coin_is_left_out(self):
        meta, ctxs = payload(ctx("OLD", 1, 1))
        meta["universe"][0]["isDelisted"] = True
        self.assertEqual(D.parse_contexts((meta, ctxs)), [])

    def test_a_normal_day_and_a_move_measured_in_it(self):
        closes = [100 * math.exp(0.02 * (1 if i % 2 else -1)) ** i for i in range(31)]
        s = D.daily_sigma(closes)
        self.assertAlmostEqual(s, np.std(np.diff(np.log(closes)), ddof=1))
        self.assertIsNone(D.daily_sigma(closes[:5]))
        rows = D.parse_contexts(payload(ctx("BTC", 103, 100)))
        D.sigmas_for(rows, lambda coin: [100.0, 101.0] * 15)
        self.assertAlmostEqual(rows[0].sigmas, rows[0].change / rows[0].sigma)
        D.sigmas_for(rows, lambda coin: 1 / 0)                                   # a failing history blanks one coin
        self.assertIsNone(rows[0].sigmas)

    def test_focus_keeps_the_lifts_order(self):
        rows = D.parse_contexts(payload(ctx("ETH", 1, 1), ctx("DOGE", 1, 1), ctx("BTC", 1, 1)))
        self.assertEqual([c.coin for c in D.focus(rows)], ["BTC", "ETH"])

    def test_movers_are_liquid_and_sorted_by_size_either_way(self):
        rows = D.parse_contexts(payload(ctx("A", 90, 100), ctx("B", 105, 100), ctx("C", 150, 100, vol="1e5"),
                                        ctx("D", 101, 100)))
        self.assertEqual([c.coin for c in D.movers(rows, n=2)], ["A", "B"])          # C trades too little

    def test_funding_is_volume_weighted_and_says_who_pays(self):
        rows = D.parse_contexts(payload(ctx("A", 1, 1, funding="0.0001", vol="3e7"),
                                        ctx("B", 1, 1, funding="-0.0001", vol="1e7")))
        f = D.funding(rows)
        self.assertEqual(f["who"], "longs pay shorts")
        self.assertAlmostEqual(f["yearly"], 0.00005 * 24 * 365)
        self.assertEqual([c.coin for c in f["crowded_long"]], ["A"])
        self.assertEqual([c.coin for c in f["crowded_short"]], ["B"])
        rest = D.parse_contexts(payload(ctx("C", 1, 1, funding=str(D.RESTING_H), vol="3e7")))
        self.assertEqual((D.funding(rest)["crowded_long"], D.funding(rest)["crowded_short"]), ([], []))
        neg = D.parse_contexts(payload(ctx("A", 1, 1, funding="-0.0001")))
        self.assertEqual(D.funding(neg)["who"], "shorts pay longs")

    def test_liquidations_sum_by_coin_whatever_the_venue_spells_it(self):
        frame = pd.DataFrame([
            {"market": "BINANCE_FUTURES:btcusdt", "lbuy": 100.0, "lsell": 5.0},
            {"market": "BYBIT:BTCUSDT", "lbuy": 50.0, "lsell": float("nan")},
            {"market": "OKEX:ETH-USDT-SWAP", "lbuy": float("nan"), "lsell": 7.0},
        ])
        self.assertEqual(D.liquidations(frame), {"BTC": {"longs": 5.0, "shorts": 150.0},
                                                  "ETH": {"longs": 7.0, "shorts": 0.0}})

    def test_liquidations_ask_aggr_at_most_every_quarter_hour(self):
        cache = Path(tempfile.mkdtemp())
        calls = []

        def fetch(start, end, markets):
            calls.append((start, end))
            return pd.DataFrame([{"market": "BYBIT:BTCUSDT", "lbuy": 1.0, "lsell": 2.0}])
        a = D.last_hour_liquidations(NOW, fetch, cache)
        b = D.last_hour_liquidations(NOW + 600, fetch, cache)
        c = D.last_hour_liquidations(NOW + 901, fetch, cache)
        self.assertEqual(len(calls), 2)
        self.assertEqual(a, b)
        self.assertEqual(c["at"], NOW + 901)
        self.assertEqual(calls[0][1] - calls[0][0], 3_600_000)
        self.assertEqual(D.last_hour_liquidations(NOW + 2000, lambda *a: 1 / 0, cache)["at"], NOW + 901)
        self.assertIsNone(D.last_hour_liquidations(NOW, lambda *a: 1 / 0, Path(tempfile.mkdtemp())))


def bars(days, sd=0.002, seed=0, start=NOW - 50 * 86_400):
    rng = np.random.default_rng(seed)
    t0 = int(start // 86_400 * 86_400)
    ts = np.array([t0 + k * 300 for k in range(days * 288)])
    close = 100 * np.exp(np.cumsum(rng.normal(0, sd, len(ts))))
    return pd.DataFrame({"close": close}, index=pd.Index(ts, name="ts"))


class TestVolatility(unittest.TestCase):
    def test_the_outlook_compares_the_forecast_with_the_last_month(self):
        from espero import volf as vf
        d = vf.daily(bars(45))
        beta = np.array([0.0, 0.0, 0.0, 1.0])                  # forecast = the 30-day mean realized variance
        o = D.outlook_from(d, beta, 1.0, "BTC")
        self.assertEqual(o.coin, "BTC")
        rv30 = d["rv"].rolling(30).mean().dropna().iloc[-1]
        self.assertAlmostEqual(o.next_week, math.sqrt(7 * rv30))
        self.assertAlmostEqual(o.last_month, math.sqrt(7 * vf.trailing_var(d["ret"], 30).dropna().iloc[-1]))
        self.assertIn(o.word, ("calmer", "about the same", "stormier"))
        storm = D.outlook_from(d, np.array([math.log(9.0), 0.0, 0.0, 1.0]), 1.0, "BTC")   # nine times the variance
        self.assertEqual(storm.word, "stormier")
        calm = D.outlook_from(d, np.array([math.log(0.1), 0.0, 0.0, 1.0]), 1.0, "BTC")
        self.assertEqual(calm.word, "calmer")
        self.assertIsNone(D.outlook_from(vf.daily(bars(10)), beta, 1.0, "BTC"))           # too few days

    def test_recent_bars_are_cached_by_day_and_a_missing_day_is_a_gap(self):
        import io
        import zipfile
        cache = Path(tempfile.mkdtemp())

        def day_zip(day):
            t0 = int(pd.Timestamp(day).timestamp() * 1000)
            lines = [f"{t0 + k * 300_000},1,1,1,{100 + k * 0.01},1,0,0,0,0,0,0" for k in range(288)]
            buf = io.BytesIO()
            with zipfile.ZipFile(buf, "w") as z:
                z.writestr("x.csv", "\n".join(lines))
            return buf.getvalue()
        asked = []

        def get(url):
            asked.append(url)
            day = url.rsplit("-5m-", 1)[1][:10]
            if day == "2026-11-03":
                raise OSError("not published yet")
            return day_zip(day)
        b = D.recent_bars("BTCUSDT", NOW, days=3, cache=cache, get=get)
        self.assertEqual(len(b), 2 * 288)
        self.assertEqual(len(asked), 3)
        D.recent_bars("BTCUSDT", NOW, days=3, cache=cache, get=get)
        self.assertEqual(len(asked), 4)                         # only the unpublished day is asked again
        self.assertTrue((cache / "klines5m" / "BTCUSDT" / "2026-11-01.zip").exists())


class TestToday(unittest.TestCase):
    def test_waiting_lists_open_proposals_in_plain_words(self):
        state = Path(tempfile.mkdtemp())
        led = approvals.Ledger.open(state / approvals.LEDGER)
        p = approvals.Proposal("ab12cd34", "machine", "8", "mf-canary", "BTC", "buy", "entry", 12.0, 60_000.0, 9.9,
                               None, "operator-paced", int(NOW), int(NOW) + 3600)
        led.record(p)
        led.db.close()
        w = D.waiting(state, int(NOW))
        self.assertEqual(len(w), 1)
        self.assertEqual((w[0].id, w[0].what, w[0].who), ("ab12cd34", "Buy BTC $12", "Rule 8 canary (weekly)"))
        self.assertEqual(w[0].by_ts, int(NOW) + 3600)
        self.assertEqual(D.waiting(state, int(NOW) + 3600), [])               # lapsed
        self.assertEqual(D.waiting(Path(tempfile.mkdtemp())), [])

    def test_system_is_one_line_from_the_watchdog_and_the_daily_job(self):
        state = Path(tempfile.mkdtemp())
        fresh = D.system(state, NOW)
        self.assertEqual((fresh.ok, fresh.fresh, fresh.problems), (True, True, ()))
        self.assertIn("fresh copy", fresh.line)
        (state / "health.json").write_text(json.dumps({"ok": True, "steps": {}}))
        self.assertIn("no watchdog report yet", D.system(state, NOW).problems)   # one has run: the other is missed
        (state / "health.json").unlink()
        (state / "watchdog.json").write_text(json.dumps({"at": NOW - 60, "checks": [{"name": "rawrec", "ok": True}]}))
        (state / "health.json").write_text(json.dumps({"ok": True, "steps": {}}))
        s = D.system(state, NOW)
        self.assertEqual((s.ok, s.line), (True, "all systems running"))
        (state / "watchdog.json").write_text(json.dumps({"at": NOW - 60, "checks": [
            {"name": "rawrec", "ok": False, "note": "silent 20 min"}]}))
        (state / "KILL").write_text("")
        s = D.system(state, NOW)
        self.assertFalse(s.ok)
        self.assertEqual(s.line, "2 things need a look")
        self.assertIn("rawrec: silent 20 min", s.problems)
        (state / "KILL").unlink()
        (state / "watchdog.json").write_text(json.dumps({"at": NOW - 3600, "checks": []}))
        self.assertIn("over 30 minutes", D.system(state, NOW).problems[0])
        self.assertEqual(D.system(state, NOW).line, "1 thing needs a look")


class TestBooks(unittest.TestCase):
    def test_the_canary_from_its_journal(self):
        from espero import mf_canary as mc
        state = Path(tempfile.mkdtemp())
        self.assertEqual(D.canary(state)["round_trips"], 0)
        db = __import__("sqlite3").connect(state / mc.DB)
        db.executescript(mc.SCHEMA)
        db.execute("INSERT INTO weeks (sunday, status) VALUES ('2026-11-01', 'late')")
        for sunday, kind, filled in (("2026-11-08", "entry", 0.1), ("2026-11-15", "exit", 0.1),
                                     ("2026-11-15", "entry", 0.2)):
            db.execute("INSERT INTO legs (sunday, coin, kind, side, status, filled) VALUES (?,?,?,?,?,?)",
                       (sunday, "BTC" if filled != 0.2 else "ETH", kind, "buy", "filled", filled))
        db.commit()
        c = D.canary(state)
        self.assertEqual((c["round_trips"], c["needed"], c["held"], c["weeks"]), (1, 10, ["ETH"], 1))
        self.assertEqual(c["last_week"], ("2026-11-01", "late"))

    def test_paper_accounts_and_the_days_to_judgment(self):
        state = Path(tempfile.mkdtemp())
        db = __import__("sqlite3").connect(state / "xs.db")
        db.execute("CREATE TABLE xs_account (id INTEGER PRIMARY KEY, ts INTEGER, equity REAL, deposit REAL)")
        db.execute("INSERT INTO xs_account (ts, equity, deposit) VALUES (1, 100, 100), (2, 93.5, 0)")
        db.commit()
        self.assertEqual(D.paper(state), [("Momentum, weekly", 93.5, 100.0)])
        self.assertEqual(D.judgment_days(time.mktime((2027, 3, 31, 0, 0, 0, 0, 0, -1))), 1)
        self.assertEqual(D.judgment_days(time.mktime((2027, 5, 1, 0, 0, 0, 0, 0, -1))), 0)


if __name__ == "__main__":
    unittest.main()
