# Forward test — the liquidator vault's inventory, the forced flow with a name (#64)

Committed **before any day of the forward window exists**: the window opens 2026-11-04, and this was
written on 2026-11-02. A paper test: nothing trades. The sixty-fourth test in this repo. It joins the
forward family by citing [PREREGISTRATION_SLEEVES.md](PREREGISTRATION_SLEEVES.md), which it cannot change.

## Why

This is idea 15 in [IDEAS_NOVEL.md](IDEAS_NOVEL.md). On Hyperliquid, a position that cannot be closed on the
book is handed to one of HLP's liquidator vaults, which hold nothing otherwise and work the position off
over the next hour or so. Their inventory is therefore forced flow by construction: it has a side, a size, an
entry price and a time, and `espero hlcollect` has read it every 15 minutes since 2026-10-29. #58 and #59
watch HLP's two strategy accounts, which are ordinary market making, void any slot in which an account
appears or goes flat, and list 14 coins; so they are built to skip exactly this (ERRATA 2026-11-02).

**The mechanism**, from #26: forced selling pushes a price further than ordinary selling does, and the
overshoot reverts. When the vault is handed a long, the fall that put it there was the cascade, and the
vault's own selling over the next hour is the last of the forced flow.

**The prediction.** After a liquidator vault is handed a position, the price moves in the vault's favour
over the next 4 hours, by more than the cost of trading it. A long handed over after a fall rises; a short
handed over after a squeeze falls.

## Data — fixed

- **The vaults.** HLP's child vaults named "HLP Liquidator" on 2026-11-02, by address, so that a read record
  can be matched at judgment:
  `0x2e3d94f0562703b25c83308a05046ddaf9a8dd14`, `0xb0a55f13d22f66e6d495ac98113841b2326e9540`,
  `0x5e177e5e39c0f4e421f5865a6d8beed8d921cb70`, `0x2ed5c4484ea3ff8b57d5f2fb152a40d9f2b68308`.
  A liquidator vault added later is information only.
- **Coins.** Every perp the vault is handed. Nothing is excluded by name.
- **Window.** Signals from 2026-11-04 00:00 UTC through 2027-03-31 23:59 UTC, 148 days. The slot before the
  window's first serves only as that slot's previous slot.
- **Positions.** `data/hlcollect/hlp/`, one file per 15-minute slot, every account of the vault. A file's
  `ts` is when its read **started**; the eight accounts are read one after another at 0.3 s apart.
- **Read records.** `data/hlcollect/hlp_reads/`, the accounts asked and those that failed, per slot.
- **Prices.** `data/hlcollect/candles/`, Hyperliquid's own 1-minute candles of every listed perp. Candles
  missing from a file may be taken from Hyperliquid's public candle API while it still serves them, and the
  count is reported. No other venue's prices are used.
- **Funding.** Hyperliquid's settled hourly rates, from its public funding history.
- **Liquidity.** `data/hlcollect/ctx/`, each coin's `day_volume` at the slot, for the tiers in the
  information section only.
- **Gaps.** A gap stays a gap. A slot missing from disk gives no signal and is never rebuilt.

## The rule — fixed

For each 15-minute slot `s` with a file on disk, `p` the slot 900 s earlier, and `ts` the file's value:

1. **Both slots exist and were read whole.** `p`'s file is on disk, and both slots' read records exist and
   list none of the four addresses as failed. Otherwise the slot gives no signal, and is counted as void.
2. **When the inventory is known.** `A = ts + 120 s`. Eight accounts at 0.3 s apart read in a few seconds;
   120 s leaves room for slow replies, and nothing in the file is used before it could have been read.
3. **New inventory.** For a vault address `a` and coin `c`: `s` holds a row for `(a, c)` with `szi ≠ 0` and
   `value ≥ $50,000`, and `p` holds no row for `(a, c)` or one of the opposite sign. The side is the sign of
   `szi` in `s`. A position that persists from `p` is not new, whatever its size.
4. **Signal.** Rule 3 holds for some vault. The signal's time is `A`, its side the vault's.
5. **Entry.** On the vault's side, at the open of the first 1-minute candle starting at least 60 s after
   `A`. If that candle isn't within 5 minutes of `A`, the trade is dropped and counted.
6. **Exit.** At the open of the first 1-minute candle starting at least 4 hours after entry. If that candle
   isn't within 5 minutes of the 4-hour mark, the trade is dropped and counted. A trade whose exit falls
   after the window is dropped.
7. **One at a time.** A coin holds one trade, across vaults. A signal during a hold is ignored, with no
   adding to it.

**Net, in bps per trade** = `side × gross − 18 − side × funding`, with `gross = 10,000 × (exit ÷ entry − 1)`
and `funding` the hourly rates settled in (entry, exit] in bps: a long pays a positive rate, a short
receives it. The 18 bps is the repo's forward hurdle, charged on every coin.

## Evaluation — once, after 2027-03-31

The headline is the **trade-weighted mean net**, with its t from `espero.audit.trade_weighted_nw`, lags = 1,
using the entry's UTC day.

**PASS requires all of these:**

1. **It pays.** Trade-weighted net > 0 with t ≥ 3.
2. **Not one stretch.** Net > 0 in each half: entries before 2027-01-17 00:00 UTC, and from then on.
3. **Not one coin.** With any one coin's trades removed, the remaining trades' mean net is still > 0. (#58's
   "coins with at least 10 trades" would qualify no coin here: the events are spread over many coins.)
4. **Not a few trades.** The median net > 0.

**INCONCLUSIVE:** fewer than 30 closed trades. **Anything else: FAIL.**

**Information only**, never a claim (`FORWARD_FAMILY.md`):

- holds of 1 hour and 1 day;
- the later entry: at the first slot after the signal's at which the vault's `|szi|` in the coin is at or
  below a quarter of its first read, entered and held as rules 5–6, in its own ledger;
- by side (long handed over, short handed over), by vault, and by liquidity tier from `day_volume` at the
  signal's slot: at least $50M, $5M to $50M, under $5M;
- gross and funding separately, and the hit rate;
- the vault's position size at the first read, and how many slots until it is flat;
- overlap with #58, #59 and #60: signals in a coin and hour where those tests also signal;
- counts of signals, void slots, dropped trades, missing slots, and slots with any liquidator row at all.

## Power — stated now

There's no prior effect size, because nothing has tested this data, so these are planning numbers only.

- **Trades.** The collector's 362 slots from 2026-10-29 15:00 UTC to 2026-11-02 09:15 UTC hold one event.
  One in about 4.5 days is about 33 in the window. The collector's coverage, the market's temper, and
  one-at-a-time all move that number, either way.
- **Noise.** Entries come straight after a cascade in whatever coin had one; about 300 bps per trade over
  4 hours is assumed, not measured.
- **What that detects.**

  | trades | net needed for t = 3, ignoring clustering |
  |---|---|
  | 30 | about +165 bps |
  | 60 | about +115 bps |

- **For scale.** The one recorded event moved about +460 bps gross from the slot's 15-minute close to the
  close 4 hours on, in a thin coin. One event says nothing about the mean.

**The author expects INCONCLUSIVE more likely than any verdict**: the expected count sits at the floor. A
FAIL on fewer than 60 trades would be weak evidence against the idea unless the estimate itself is near or
below zero. The test's first value is the ledger of named forced flows it leaves behind.

## Outcomes, fixed now

- **PASS**: treated as a Tier A pass under `FORWARD_FAMILY.md`, rule 2: a real-money sizing and execution
  document, written before any order, on a venue from [VENUE_NONUS.md](VENUE_NONUS.md). The account holder
  checks eligibility and places any order. Costs in the thin coins are the first thing that document must
  measure, from the raw tape where it records the coin and from #51's method where it does not.
- **FAIL**: this rule is closed. A later idea on the liquidator vaults takes a new number and a new document.
- **INCONCLUSIVE**: no claim either way, and no extension of this test. Any continuation is a new document.

No stopping early on the running numbers, and no re-tuning of the dust floor, the margin, the hold or the
addresses. The collector is not changed for this test: a faster read of the four addresses would be a new
recording and a new document.

The ledger's code is `espero/liqvault.py`, run once with `espero liqvault --verdict` after the window has
closed. It refuses to read the recordings before then. There's no paper book, and this document starts no new
process.

## Known confounds

- **Costs.** 18 bps straight after an 18% fall in a coin that trades $50k a quarter-hour in calm is not a
  round trip; it is the repo's hurdle, kept so that results compare across tests. This is the headline
  risk, and the liquidity tiers are there to show where the mean comes from.
- **Late by up to 15 minutes.** The collector reads every 15 minutes, so the vault is seen 0 to 15 minutes
  after it was handed the position, and the entry comes 2 to 3 minutes after that. The test measures
  whether the bounce outlives that latency, not whether it exists at the moment of liquidation.
- **A slower read.** Rule 2 assumes a read ends within 120 s. The file doesn't record when it finished.
- **The vault is still selling at entry.** Taking the vault's side means buying into its unwind; that is the
  mechanism, and it is also where the first hour's return can be negative.
- **Not every liquidation lands here.** Most are closed on the book and never reach a vault; the test sees
  only the ones the book could not absorb, which are the largest and in the thinnest coins.
- **Four addresses.** A liquidator vault added or retired after 2026-11-02 is not in the rule.
- **One at a time hides the cluster.** A sell-off that hands several coins over at once gives several
  trades on one day; the t is day-clustered for that, with lags.
- **Related to the forced-liquidation family.** Signals may coincide with #26's, #27's, #32's, #45's, #58's,
  #59's and #60's events. A pass alongside those isn't fully independent. The overlap is reported.
- **Coverage.** Slots are lost when the Mac sleeps, and sleep during sell-offs would remove the events this
  test needs.
- **The thresholds have no data behind them.** The $50,000 floor, the 120 s margin and the 30-trade floor
  are the author's choices. The 60 s delay, 5-minute tolerance, 4-hour hold and 18 bps follow #58.

## Transparency — what was seen before this

- **Seen in writing this, from the recordings, all before the window opens:** every `hlp` file from
  2026-10-29 to 2026-11-02 09:15 UTC was scanned for rows of the vault's own address, Strategy X, or any
  liquidator; five rows were found, one position of Liquidator 3 in XPL across the slots from 04:45 to
  05:45 UTC on 2026-11-01, with its size, entry price, value and unrealised loss at each read; XPL's
  1-minute candles for 2026-11-01 from 03:00 to 09:00 UTC, as 15-minute closes and volumes; the vault's
  public details and each child's account value on 2026-11-02 (ERRATA 2026-11-02); the top accounts'
  BTC and ETH liquidation prices in the 08:00 UTC positions file of 2026-11-02, which this test does not
  use.
- **What that event looked like.** The vault held a long handed over after an 18% fall; the price rose about
  3.4% while the vault sold and was about 4.6% above the slot's close four hours later. The rule above was
  written after seeing it. The hold, delay, tolerance and cost were not chosen from it: they are #58's.
  The dust floor and the 120 s margin were chosen before any second event exists.
- **Not seen:** any other event, any return of the rule over the recordings, the information-only variants.
- **A limit on that.** Earlier work may have opened these files. This can only speak to what the repo records.
- **Already known:** #26's and #44's forced-liquidation results, #51's costs, #52–#57's microstructure
  measurements, and the designs of #58, #59 and #60. #58 and #59 read the same files for other accounts.
- **No day of the forward window exists yet.**
