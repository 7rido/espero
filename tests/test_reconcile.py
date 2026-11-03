import unittest

from espero import reconcile as rc


def fill(oid, px, sz, crossed, fee=None, rate=None):
    fee = px * sz * rate if fee is None else fee
    return {"oid": oid, "px": str(px), "sz": str(sz), "crossed": crossed, "fee": str(fee), "tid": 1}


MAKER, TAKER = 0.00015, 0.00045
STEP = {1: 0.00001, 2: 0.00001, 3: 0.00001}
TICK = {1: 1.0, 2: 1.0, 3: 1.0}


class TestStartup(unittest.TestCase):
    """reconcile.startup: what an executor checks before its first order after any start."""

    def test_agreement_is_no_break(self):
        self.assertEqual(rc.startup({"BTC": 0.01}, {"BTC": 0.01}, ["c1"], ["c1"], {"BTC": 0.001}), [])

    def test_a_position_the_journal_does_not_know(self):
        out = rc.startup({}, {"ETH": -0.5}, [], [], {"ETH": 0.01})
        self.assertEqual(out, ["ETH: the venue holds -0.5 that the journal does not know"])

    def test_a_position_the_venue_does_not_hold_and_a_size_off(self):
        out = rc.startup({"BTC": 0.01, "SOL": 2.0}, {"SOL": 1.0}, [], [], {"BTC": 0.001, "SOL": 0.1})
        self.assertEqual(out, ["BTC: the journal holds +0.01 that the venue does not",
                               "SOL: the journal holds +2, the venue +1"])

    def test_half_a_step_is_agreement(self):
        self.assertEqual(rc.startup({"BTC": 0.0104}, {"BTC": 0.01}, [], [], {"BTC": 0.001}), [])

    def test_orders_unknown_and_lost(self):
        out = rc.startup({}, {}, ["a", "b"], ["b", "c"], {})
        self.assertEqual(out, ["order c: resting on the venue, unknown to the journal",
                               "order a: the journal says resting, the venue does not list it (filled or cancelled?)"])

    def test_a_shared_account_compares_only_its_own_orders(self):
        out = rc.startup({}, {"ETH": -0.5}, ["a"], ["a", "someone-elses"], {}, owns_account=False)
        self.assertEqual(out, [])
        self.assertEqual(len(rc.startup({}, {}, ["a"], [], {}, owns_account=False)), 1)


class TestFills(unittest.TestCase):
    """#40's criteria on fills, fees, flags, post-only refusals, positions and markouts."""

    def test_by_oid_sums_partial_fills(self):
        g = rc.by_oid([fill(1, 100, 0.1, False, rate=MAKER), fill(1, 102, 0.3, False, rate=MAKER)])
        assert abs(g[1]["sz"] - 0.4) < 1e-12 and abs(g[1]["avg_px"] - 101.5) < 1e-9 and g[1]["n"] == 2

    def test_clean_session_has_no_breaks(self):
        ours = {1: {"tif": "Alo", "filled": 0.0002, "avg_px": None},
                2: {"tif": "Ioc", "filled": 0.0002, "avg_px": 80000.0},
                3: {"tif": "Alo", "filled": 0.0, "avg_px": None}}             # cancelled unfilled
        fills = [fill(1, 79990, 0.0002, False, rate=MAKER), fill(2, 80000, 0.0002, True, rate=TAKER)]
        assert rc.fills_match(ours, fills, STEP, TICK) == []
        assert rc.fees_match(fills, MAKER, TAKER) == []
        assert rc.flags_match(ours, fills) == []

    def test_missing_on_either_side_is_a_break(self):
        ours = {1: {"tif": "Alo", "filled": 0.0002, "avg_px": None}}
        assert any("no fill" in b for b in rc.fills_match(ours, [], STEP, TICK))
        stray = [fill(2, 100, 0.1, True, rate=TAKER)]
        assert any("not in our record" in b for b in rc.fills_match({}, stray, STEP, TICK))

    def test_size_and_price_disagreements(self):
        ours = {1: {"tif": "Alo", "filled": 0.0003, "avg_px": None},
                2: {"tif": "Ioc", "filled": 0.0002, "avg_px": 80002.0}}
        fills = [fill(1, 79990, 0.0002, False, rate=MAKER), fill(2, 80000, 0.0002, True, rate=TAKER)]
        b = rc.fills_match(ours, fills, STEP, TICK)
        assert any("size" in x for x in b) and any("avg price" in x for x in b)
        ours[2]["avg_px"] = 80001.0                                           # one tick: allowed
        assert not any("avg price" in x for x in rc.fills_match(ours, fills, STEP, TICK))

    def test_fee_uses_the_rate_for_the_side_that_was_taken(self):
        ok = [fill(1, 100, 1, False, rate=MAKER), fill(2, 100, 1, True, rate=TAKER)]
        assert rc.fees_match(ok, MAKER, TAKER) == []
        wrong = [fill(1, 100, 1, False, rate=TAKER)]                          # maker fill charged taker
        assert len(rc.fees_match(wrong, MAKER, TAKER)) == 1
        tiny = [fill(1, 100, 1, False, fee=100 * MAKER + 5e-7)]               # rounding within tolerance
        assert rc.fees_match(tiny, MAKER, TAKER) == []

    def test_flags_follow_the_order_type(self):
        ours = {1: {"tif": "Alo", "filled": 1, "avg_px": None}, 2: {"tif": "Ioc", "filled": 1, "avg_px": 100}}
        assert rc.flags_match(ours, [fill(1, 100, 1, False, rate=MAKER), fill(2, 100, 1, True, rate=TAKER)]) == []
        assert len(rc.flags_match(ours, [fill(1, 100, 1, True, rate=TAKER)])) == 1     # a post-only that took
        assert len(rc.flags_match(ours, [fill(2, 100, 1, False, rate=MAKER)])) == 1    # an IOC that made

    def test_post_only_refusal(self):
        refused = [{"coin": "BTC", "side": "buy", "price": 1, "status": "error", "oid": None}]
        assert rc.post_only_refused(refused, []) == []
        rested = [{"coin": "BTC", "side": "buy", "price": 1, "status": "resting", "oid": 7}]
        assert len(rc.post_only_refused(rested, [])) == 1
        took = [{"coin": "BTC", "side": "buy", "price": 1, "status": "filled", "oid": 8}]
        assert len(rc.post_only_refused(took, [fill(8, 1, 1, True, rate=TAKER)])) == 2

    def test_positions_match_within_half_a_step(self):
        assert rc.positions_match({"BTC": 0.00014}, {"BTC": 0.00014}, {"BTC": 0.00001}) == []
        assert rc.positions_match({"BTC": 0.0}, {}, {"BTC": 0.00001}) == []                 # flat = missing
        b = rc.positions_match({"BTC": 0.0}, {"BTC": 0.00011}, {"BTC": 0.00001})            # #40's leftover
        assert len(b) == 1 and "BTC" in b[0]
        assert len(rc.positions_match({}, {"ETH": -0.01}, {"ETH": 0.0001})) == 1           # unintended short

    def test_fill_markouts_take_the_makers_side_and_need_a_recent_row(self):
        book = [(1000, "BTC", 100.0), (2000, "BTC", 101.0), (11_000, "BTC", 99.0), (61_500, "BTC", 102.0),
                (400_000, "BTC", 90.0)]                                  # far past +300 s: too stale to use
        fills = [{"oid": 1, "coin": "BTC", "side": "B", "px": "100", "time": "1000", "crossed": False},
                 {"oid": 2, "coin": "BTC", "side": "A", "px": "100", "time": "1000", "crossed": False}]
        m = rc.fill_markouts(fills, book, horizons_s=(1, 10, 60, 300))
        assert abs(m[0][1] - 100.0) < 1e-9 and abs(m[1][1] + 100.0) < 1e-9                 # +1% for the buyer
        assert abs(m[0][10] + 100.0) < 1e-9                                                 # mid 99 at +10 s
        assert abs(m[0][60] - 200.0) < 1e-9                                                 # 61.5 s is within 2 s
        assert m[0][300] is None                                                            # nothing near +300 s


if __name__ == "__main__":
    unittest.main()
