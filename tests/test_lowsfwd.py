"""#24's recorder and ledger: recent days waited for, old gaps given up on, and
breakdowns bought at the next open and sold 4 hours later."""
from __future__ import annotations

import io
import tempfile
import unittest
import unittest.mock
import zipfile
from pathlib import Path

import pandas as pd

from espero import lowsfwd as lf
from tests.test_liq import at, plant_up, quiet
from tests.test_lows import flipped

D0 = int(pd.Timestamp("2026-10-30", tz="UTC").timestamp())


def zipped(bars: pd.DataFrame) -> bytes:
    rows = [f"{t * 1000},{r.open},{r.high},{r.low},{r.close},{r.volume},{t * 1000 + 299999},0,0,0,0,0"
            for t, r in bars.iterrows()]
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("x.csv", "\n".join(rows) + "\n")
    return buf.getvalue()


class TestRecord(unittest.TestCase):
    def test_wait_for_recent_days_give_up_on_old_ones(self):
        now = pd.Timestamp("2026-11-12 09:00", tz="UTC")
        published = {"2026-10-29", "2026-10-30", "2026-11-10"}
        with tempfile.TemporaryDirectory() as d, unittest.mock.patch.object(lf, "UNIVERSE", ["BTC"]):
            blob = zipped(pd.DataFrame())
            c = lf.record(Path(d), now, lambda url: blob if url.rsplit("-5m-", 1)[1][:10] in published else None)
            self.assertEqual(c["saved"], 3)
            self.assertEqual(c["waiting"], 6)             # Nov 5-9 and 11: a week old or less, tried again tomorrow
            self.assertEqual(c["missing"], 5)             # Oct 31 - Nov 4: more than a week, given up on
            again = lf.record(Path(d), now, lambda url: None)
            self.assertEqual((again["saved"], again["waiting"], again["missing"]), (0, 6, 0))

    def test_a_download_that_is_not_a_whole_zip_is_never_saved(self):
        """A truncated download saved as the day's file would be skipped by every later run and break every
        step that reads it; it is refused before it lands, and the day is asked again next run."""
        now = pd.Timestamp("2026-11-12 09:00", tz="UTC")
        with tempfile.TemporaryDirectory() as d, unittest.mock.patch.object(lf, "UNIVERSE", ["BTC"]):
            whole = zipped(pd.DataFrame())
            with self.assertRaises(zipfile.BadZipFile):
                lf.record(Path(d), now, lambda url: whole[: len(whole) // 2])
            self.assertEqual(list(Path(d).rglob("*.zip")) + list(Path(d).rglob("*.tmp")), [])


class TestLedger(unittest.TestCase):
    def test_a_breakdown_bought_at_the_next_open_sold_4_hours_later(self):
        t = at(10, day=D0)
        b = flipped(plant_up(quiet(day_start=D0), t))
        with tempfile.TemporaryDirectory() as d, unittest.mock.patch.object(lf, "UNIVERSE", ["BTC"]):
            folder = Path(d) / "BTCUSDT"
            folder.mkdir()
            for k, day in enumerate(("2026-10-29", "2026-10-30", "2026-10-31")):
                start = D0 + (k - 1) * 86400
                (folder / f"{day}.zip").write_bytes(zipped(b[(b.index >= start) & (b.index < start + 86400)]))
            led = lf.ledger(Path(d))
        self.assertEqual(len(led), 1)
        e = led.iloc[0]
        self.assertEqual(e["day"], "2026-10-30")
        self.assertAlmostEqual(e["ret"], b.loc[t + 48 * 300, "close"] / b.loc[t + 300, "open"] - 1)


if __name__ == "__main__":
    unittest.main()
