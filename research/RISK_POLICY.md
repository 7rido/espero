# The account's risk policy: the gate every order passes

**Written 2026-11-02, before any forward verdict and before any sleeve exists.** These are the account-level
limits every order that could reach a venue passes, fixed with their reasoning while no result can shape them.
`espero.risk.check` is the gate, `espero.risk.Policy` holds the numbers, and `tests/test_risk.py` fails when the
table below and the code disagree. It decides no verdict and changes no frozen test.

## Where the gate sits

```
a rule's event  ->  #63's sleeves (weights, drawdown states)  ->  edgewatch (#70)  ->  the ladder's rung
                ->  risk.check (this policy)  ->  the operator, if operator-paced (docs/OPERATOR.md)  ->  the venue
```

#63's sleeves sit above the gate and cannot bypass it: their weight, the ladder's rung, the drawdown state and
edgewatch's scale reach the gate as one number per sleeve (`Account.sleeve_scale`), and the gate's caps bind on
top of it. A sleeve with no scale has no allocation, and the gate refuses it. The per-book limits in `risk.py`'s
first half (`RiskLimits`, `check_buy`) belong to the paper books (paper.py, degen.py), which reach no venue; they
are unchanged.

## What the numbers are fractions of

Every cap is a fraction of the **base**: the smaller of the holder's allocated capital and the account's marked
equity, so the caps shrink with losses and never grow past the allocation. The allocation is the holder's answer in
docs/HOLDER_INPUTS.md. **Until it is answered the allocation is 0 and the gate refuses every entry.** Capital,
drawdown tolerance and venue eligibility are the holder's inputs; nothing here assumes them.

## The numbers

<!-- policy:start -->
| field | value | what it bounds | why this number |
|---|---|---|---|
| `leverage` | 1.0 | gross perp notional over the base, the whole account | #63: "this repo does not borrow"; a sleeve never runs above 1.0x its notional and the book's gross is capped at 100 %. At 1x a long is liquidated only near zero, a short only after the price nearly doubles. |
| `venue_leverage` | 1.0 | gross perp notional on one venue over the equity held there | the same rule per venue, so a venue's margin is never borrowed from another's |
| `per_coin` | 0.20 | gross perp notional in one coin over the base | at a 10 % vol target and a coin's 60-100 % a year, 20 % in one coin already carries the whole book's target; a 30 % gap in that coin costs 6 % of the base, inside the week stop |
| `per_venue` | 0.50 | gross notional on one venue, every leg, over the base | a venue failure (FTX in 2022; Hyperliquid's JELLY and HLP episodes in 2025) costs at most half. With one eligible venue the system runs at half size: that is the price of the rule |
| `per_sleeve` | 1.0 | a sleeve's gross over the base, times its scale | the scale is #63's weight (1.0 alone) x the ladder's rung x #63's drawdown state x edgewatch's state; this cap only stops a scale above 1 |
| `liq_floor` | 0.25 | the adverse move the venue's whole perp book must survive before maintenance margin | at 1x it never binds; it catches cross-margin mistakes and a venue raising its margins |
| `liq_sigmas` | 8.0 | the same, in the coin's trailing 30-day daily sigmas, whichever is larger | BTC at 2.5 % a day needs 20 % (the floor binds); an alt at 6 % a day needs 48 % |
| `funding_day` | 0.0020 | funding paid over the next 24 hours at current rates, every position, over the base | 0.20 % a day is about 73 % a year: a book paying that is in a squeeze (#67's squeezed listings paid 2.7 % a position on average) |
| `funding_position` | 0.0010 | the same for one position | half the total, so no single position can use the whole allowance |
| `day_stop` | -0.02 | equity against its 00:00 UTC value | at a 10 % annual vol target the book's daily sigma is about 0.52 % (365 days), so -2 % is a 3.8-sigma day: rare by chance, a sign something broke |
| `week_stop` | -0.05 | equity against its Monday 00:00 UTC value | weekly sigma about 1.39 %, so -5 % is about 3.6 sigma |
| `hedge_tolerance` | 0.02 | a two-legged trade's spot minus perp, over its larger leg | a carry trade's legs fill one at a time and in pieces; past 2 % it is a directional position nobody registered |
<!-- policy:end -->

## What the gate does to an order

- **An entry** is checked in this order: an allocation exists; no stop is in force (below); no week stop awaits its
  acknowledgement; nothing is paused (`KILL`, an executor's `.stop`, attribution's `.pause`); no reconciliation or
  hedge break is open; the sleeve has an allocation. Then every cap gives its room, and the order is **cut to the
  smallest room**, or **refused** when that is under the venue's minimum. The ruling lists every cap that bound.
- **A reduce-only order** always passes the caps, cut to what is held on that side, and is journaled. A reduce-only
  order with nothing to reduce is refused.
- **Every ruling** carries the policy's hash (`risk.policy_hash`), so a journal records which numbers allowed which
  order.

## The stops, and what they do to open positions

| stop | when | resting orders | open positions | new entries |
|---|---|---|---|---|
| **day** | equity at or below -2 % of its 00:00 UTC value | entry orders cancelled | run to their registered exits: flattening early would make the live trade another than the tested one | none until 00:00 UTC |
| **week** | at or below -5 % of its Monday 00:00 UTC value | every order cancelled | **flattened**, reduce-only, perp legs first | none until next Monday 00:00 UTC **and** the operator's authenticated acknowledgement |
| **holder** | at or below the holder's own drawdown from the peak (docs/HOLDER_INPUTS.md) | every order cancelled | **flattened**, reduce-only, perp legs first | none until the holder changes the number |

These are distinct from #63's sleeve states (-10 % halves a sleeve, -20 % flattens it, from its own peak) and from
edgewatch's (#70), which test whether the edge is still the registered one. The gate takes the smallest scale of
all of them, and its stops apply to the whole account on calendar windows.

## Two legs: what "flat" means for carry

A carry trade is a short perp and a long spot. **Flat means both legs at zero.** The perp leg is closed first: it is
the one that can be liquidated and that pays funding, while a fully paid spot leg left alone can lose only what it
holds (`risk.flatten_orders`). Between the two closes the trade is unwinding, not flat. A trade whose legs differ by
more than 2 % of the larger leg is a **break** (`risk.hedge_breaks`), and an open break refuses every entry on the
account until it is reconciled. Spot legs count toward the per-venue and per-sleeve caps, not toward leverage,
per-coin or funding.

## Who may change a number, and how a change is logged

- **The holder, and only the holder,** in a commit that edits this table and `espero.risk.Policy` together. The
  test fails when they differ, so neither can move alone. An agent may propose a change in prose; it does not make
  one.
- The commit message gives each old and new value and the reason. A row is added to "Changes" below.
- The new policy hash appears in every ruling from then on, so the journal shows when it took effect.
- `python -m espero.risk` prints the numbers, any disagreement with this table, and the hash.

## What it does not cover

- Slippage and fill quality: those are the ladder's measurements (research/DEPLOYMENT_LADDER.md) and #62's.
- A venue's own outage or insolvency beyond the per-venue cap.
- Exchange-side stop orders: a stop that survives the machine's crash is part of the mainnet design
  (research/DESIGN_MAINNET_PATH.md), not of this gate.
- Liquidation distance is estimated conservatively, as if every position on the venue moved against itself at once;
  where the venue reports a liquidation price, the gate also refuses entries while any position is inside the bound.

## Changes

| date | field | old | new | who | why | commit |
|---|---|---|---|---|---|---|
| 2026-11-02 | every field | — | as above | this document, before any verdict | the first policy | this commit |
