"""打板 on Hyperliquid: the coin list from its 24h volumes, its perp bars, and the
defaults that keep Coinbase and Hyperliquid books apart."""
from __future__ import annotations

import contextlib
import io
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import pandas as pd

from espero import cli, data
from espero import hyperliquid as hl
from tests.test_degen import bars, plant_breakout


def ctxs(_body):
    names = ["BTC", "ETH", "SOL", "kPEPE", "HYPE", "OLD"]
    meta = {"universe": [{"name": n} for n in names[:-1]] + [{"name": "OLD", "isDelisted": True}]}
    rows = [("100000", "9e9"), ("3000", "8e9"), ("150", "1e9"), ("0.012", "3e9"), ("40", "2e9"), ("1", "9e12")]
    return [meta, [{"markPx": px, "funding": "0", "openInterest": "1", "dayNtlVlm": v} for px, v in rows]]


class TestUniverse(unittest.TestCase):
    def setUp(self):
        self.coin, self.unit = dict(hl.COIN), dict(hl.UNIT)
        self.addCleanup(lambda: (hl.COIN.clear(), hl.COIN.update(self.coin),
                                 hl.UNIT.clear(), hl.UNIT.update(self.unit)))

    def test_ranked_by_dollar_volume_without_majors_or_delisted(self):
        uni = hl.degen_universe(top=10, fetch=ctxs)
        self.assertEqual([u["product"] for u in uni], ["PEPE-USD", "HYPE-USD", "SOL-USD"])
        self.assertEqual(uni[0]["dollar_volume"], 3e9)

    def test_a_per_thousand_perp_is_priced_per_coin(self):
        uni = hl.degen_universe(top=10, fetch=ctxs)
        self.assertAlmostEqual(uni[0]["last"], 0.012 / 1000)
        self.assertEqual(hl.hl_coin("PEPE-USD"), "kPEPE")
        self.assertEqual(hl.UNIT["kPEPE"], 1000.0)

    def test_per_thousand_perps_are_registered_even_outside_the_top(self):
        hl.degen_universe(top=1, fetch=ctxs)
        self.assertEqual(hl.hl_coin("PEPE-USD"), "kPEPE")         # top 1 is PEPE anyway
        hl.COIN.pop("PEPE")
        uni = hl.degen_universe(top=1, exclude=("BTC", "ETH", "PEPE"), fetch=ctxs)
        self.assertEqual([u["product"] for u in uni], ["HYPE-USD"])
        self.assertEqual(hl.hl_coin("PEPE-USD"), "kPEPE")         # a held PEPE still prices


class TestDefaults(unittest.TestCase):
    def parse(self, *argv):
        return cli._degen_defaults(cli.build_parser().parse_args(["degen", *argv]))

    def test_hyperliquid_is_the_default_source_venue_and_book(self):
        a = self.parse("paper")
        self.assertEqual((a.source, a.venue, Path(a.state).name), ("hyperliquid", "hyperliquid", "degen-hl.db"))
        self.assertEqual(Path(a.state).parent, cli.state_dir())     # the book lives with the accounts

    def test_coinbase_keeps_the_forward_test_book(self):
        a = self.parse("paper", "--source", "coinbase")
        self.assertEqual((a.venue, Path(a.state).name), ("binanceus", "degen.db"))

    def test_explicit_choices_win(self):
        a = self.parse("paper", "--venue", "kraken", "--state", "x.db")
        self.assertEqual((a.venue, a.state), ("kraken", "x.db"))

    def test_backtest_replays_hyperliquid_fees_by_default(self):
        self.assertIn("hyperliquid", self.parse("backtest").venues.split(","))


class TestFeeds(unittest.TestCase):
    def test_scan_reads_hyperliquid_bars_not_coinbase(self):
        uni = [{"product": "AAA-USD", "dollar_volume": 5e6}]
        with mock.patch.object(hl, "degen_universe", return_value=uni) as u, \
                mock.patch.object(hl, "closed_bars", side_effect=lambda p, g, n: plant_breakout(bars())) as hb, \
                mock.patch.object(data, "recent_closed_bars", side_effect=AssertionError("coinbase")), \
                mock.patch.object(data, "degen_universe", side_effect=AssertionError("coinbase")), \
                contextlib.redirect_stdout(io.StringIO()) as out:
            self.assertEqual(cli.main(["degen", "scan", "--top", "1"]), 0)
        u.assert_called_once()
        self.assertEqual(hb.call_args.args[0], "AAA-USD")
        self.assertIn("Hyperliquid perps", out.getvalue())

    def test_paper_loop_reads_hyperliquid_bars(self):
        with tempfile.TemporaryDirectory() as d:
            args = cli.build_parser().parse_args(["degen", "paper", "--state", str(Path(d) / "d.db")])
            seen = []
            with mock.patch.object(cli, "_degen_universe", return_value=[{"product": "AAA-USD",
                                                                          "dollar_volume": 5e6}]), \
                    mock.patch.object(hl, "closed_bars", side_effect=lambda p, g, n: seen.append(p) or bars()), \
                    mock.patch.object(data, "recent_closed_bars", side_effect=AssertionError("coinbase")), \
                    mock.patch("time.sleep"), contextlib.redirect_stdout(io.StringIO()):
                cli._degen_loop(args)
        self.assertEqual(seen, ["AAA-USD"])

    def test_backtest_caps_days_at_the_bar_limit_and_caches_apart(self):
        with tempfile.TemporaryDirectory() as d:
            calls = []

            def hl_bars(p, gran, limit):
                calls.append((p, gran, limit))
                df = plant_breakout(bars(200))
                df["dt"] = pd.to_datetime(df["ts"], unit="s", utc=True)
                return df

            with mock.patch.object(cli, "_degen_universe",
                                   return_value=[{"product": "AAA-USD", "dollar_volume": 5e6}]), \
                    mock.patch.object(hl, "closed_bars", side_effect=hl_bars), \
                    mock.patch.object(data, "fetch", side_effect=AssertionError("coinbase")), \
                    mock.patch("time.sleep"), contextlib.redirect_stdout(io.StringIO()) as out:
                self.assertEqual(cli.main(["degen", "backtest", "--cache", d]), 0)
            self.assertEqual(calls, [("AAA-USD", 300, 4896)])            # 17 days of 5m bars
            self.assertEqual([f.name for f in Path(d).iterdir()], ["AAAUSD_300s_17d_hl.csv"])
            text = out.getvalue()
            self.assertIn("Hyperliquid serves the last 5,000 bars: 17 days of 5m bars, not 30", text)
            self.assertIn("Hyperliquid (base tier)", text)
            self.assertIn("information only", text)
            self.assertIn("replaying 1 coins x 17d", text)


if __name__ == "__main__":
    unittest.main(verbosity=2)
