"""#27: aggr's 5-minute bars as liquidation rows, and the ledger built from them and
#24's Binance bars, with each break's forced share and group."""
from __future__ import annotations

import gzip
import io
import tempfile
import unittest
import zipfile
from pathlib import Path

import pandas as pd

from espero import liqbreak as lb
from tests.test_liq import at, plant_up, quiet
from tests.test_lows import flipped

D0 = int(pd.Timestamp("2026-11-02", tz="UTC").timestamp())


def kline_zip(b: pd.DataFrame) -> bytes:
    rows = [f"{t * 1000},{r.open},{r.high},{r.low},{r.close},{r.volume},{t * 1000 + 299999},1000,1,0,600,0"
            for t, r in b.iterrows()]
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("x.csv", "\n".join(rows) + "\n")
    return buf.getvalue()


def aggr_day(t_liq: int, usd: float) -> bytes:
    rows = ["time,market,open,high,low,close,vbuy,vsell,cbuy,csell,lbuy,lsell",
            f"{t_liq},BINANCE_FUTURES:btcusdt,1,1,1,1,1,1,1,1,0,{usd}",
            f"{t_liq},BYBIT:BTCUSDT,1,1,1,1,1,1,1,1,7,{usd}",
            f"{t_liq},OKEX:ETH-USDT-SWAP,1,1,1,1,1,1,1,1,0,99999"]          # another coin: not BTC's
    return gzip.compress(("\n".join(rows) + "\n").encode())


class TestRows(unittest.TestCase):
    def test_longs_and_shorts_per_bar_summed_over_the_coins_venues(self):
        raw = pd.read_csv(io.BytesIO(gzip.decompress(aggr_day(D0, 500.0))))
        r = lb.liq_rows(raw, "BTC")
        self.assertEqual(sorted(zip(r["side"], r["usd"])), [("buy", 7.0), ("sell", 1000.0)])
        self.assertEqual(set(r["ts"]), {float(D0)})


class TestLedger(unittest.TestCase):
    def test_a_forced_down_break_gets_its_share_and_returns(self):
        t = at(10, day=D0)
        b = flipped(plant_up(quiet(day_start=D0), t))
        with tempfile.TemporaryDirectory() as d:
            bars_dir, aggr_dir = Path(d) / "bars" / "BTCUSDT", Path(d) / "aggr"
            bars_dir.mkdir(parents=True)
            aggr_dir.mkdir()
            for k in (-1, 0, 1):
                start = D0 + k * 86400
                day = pd.Timestamp(start, unit="s").strftime("%Y-%m-%d")
                (bars_dir / f"{day}.zip").write_bytes(kline_zip(b[(b.index >= start) & (b.index < start + 86400)]))
            (aggr_dir / "2026-11-02.csv.gz").write_bytes(aggr_day(t - 300, 2000.0))     # inside the break's hour
            led = lb.ledger(aggr_dir, Path(d) / "bars")
        e = led[(led["coin"] == "BTC") & (led["direction"] == -1)].iloc[0]
        self.assertEqual(e["forced"], 4000.0)                         # longs liquidated: Binance + Bybit
        self.assertGreater(e["s"], 0)
        self.assertLess(e["y60"], 0)                                  # the mirrored fade: a bounce up

    def write_bars(self, root, symbol, b):
        folder = Path(root) / "bars" / symbol
        folder.mkdir(parents=True)
        for k in (-1, 0, 1):
            start = D0 + k * 86400
            day = pd.Timestamp(start, unit="s").strftime("%Y-%m-%d")
            (folder / f"{day}.zip").write_bytes(kline_zip(b[(b.index >= start) & (b.index < start + 86400)]))

    def test_a_coin_with_no_breaks_does_not_stop_the_others(self):
        t = at(10, day=D0)
        with tempfile.TemporaryDirectory() as d:
            self.write_bars(d, "BTCUSDT", flipped(plant_up(quiet(day_start=D0), t)))
            self.write_bars(d, "ETHUSDT", quiet(day_start=D0))
            aggr_dir = Path(d) / "aggr"
            aggr_dir.mkdir()
            (aggr_dir / "2026-11-02.csv.gz").write_bytes(aggr_day(t - 300, 2000.0))
            led = lb.ledger(aggr_dir, Path(d) / "bars")
        self.assertEqual(set(led["coin"]), {"BTC"})
        self.assertTrue(pd.api.types.is_float_dtype(led["y60"]))

    def test_a_day_with_no_breaks_at_all_keeps_its_columns(self):
        with tempfile.TemporaryDirectory() as d:
            self.write_bars(d, "ETHUSDT", quiet(day_start=D0))
            aggr_dir = Path(d) / "aggr"
            aggr_dir.mkdir()
            (aggr_dir / "2026-11-02.csv.gz").write_bytes(aggr_day(D0, 2000.0))
            led = lb.ledger(aggr_dir, Path(d) / "bars")
        self.assertTrue(led.empty)
        self.assertIn("y60", led.columns)


if __name__ == "__main__":
    unittest.main()
