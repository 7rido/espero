# Who absorbs a forced liquidation on Hyperliquid — mechanism memo

**Status: approved by the user, 2026-10-31. Written before any market data for this study was read.** It takes no test number
and spends no trial; registration is step 4. Rules come from Hyperliquid's documentation as read on 2026-10-31. Those
pages are a description of the protocol, not proof of what the engine does, so C1–C4 test them against fills.

**Constraints set by the user:** $5,000 research capital, $400 a year fixed costs, stop under $2,000 a year. Hours were
written as "80r", read here as 80 a week; please confirm. The threshold is read as **after** fixed costs; please confirm.

## 1. The rules

| stage | trigger | what happens | who takes the other side |
|---|---|---|---|
| **Book liquidation** | equity below maintenance margin, on the mark price | market orders for the whole position. Over $100,000: only 20% at a time, then a 30-second cooldown during which orders cover the entire position | whoever rests in the book |
| **Backstop** | equity below 2/3 of maintenance, book step unsuccessful | the Liquidator Vault, part of HLP, takes the position. Cross: all cross positions and margin. Isolated: that position and its margin. **The maintenance margin is not returned** | HLP's Liquidator Vault |
| **Auto-deleveraging** | account or isolated position value negative | profitable opposite-side traders, ranked by `(mark / entry) × (notional / account value)`, are closed at the previous mark | those traders, unwillingly |

- **Maintenance margin** is half the initial margin at maximum leverage: 1.25% at 40x, 16.7% at 3x.
- **Mark price** combines outside exchange prices with Hyperliquid's own book. The **oracle** is a weighted median of
  exchange spot prices.
- **Funding** is `P + clamp(interest − P, −0.0005, 0.0005)` on an 8-hour basis, paid hourly at one-eighth, capped at 4% an
  hour. P averages a premium from impact prices, sampled every 5 seconds over the hour. Interest is fixed at 0.01% per
  8 hours, which is about 11.6% a year paid to shorts when the premium is zero.
- **Fees at the base tier:** 4.5 bps taker, 1.5 bps maker. No clearance fee on liquidations. Liquidation profit goes to
  HLP, by the docs "on average profitable".
- **Labels:** a user's fill carries `liquidation: {liquidatedUser, markPx, method: "market" | "backstop"}`. The public
  trades channel shows both addresses and carries no liquidation flag.

## 2. Claims, and what would falsify each

### What the engine does

| # | claim | falsified if |
|---|---|---|
| C1 | Most forced volume clears in the book, not the backstop | backstop's share of liquidated notional is above 50% |
| C2 | Positions over $100,000 start at 20% clips | clips of these positions regularly exceed 20% outside a cooldown |
| C3 | The backstop keeps the maintenance margin | the vault's entry, against the mark, does not reflect the forfeit |
| C4 | Auto-deleveraging happens only when an account goes negative, in the stated rank order | it hits accounts out of order, or with no account negative |

### Who absorbs, and why they would be paid

| # | claim | why they are paid | falsified if |
|---|---|---|---|
| C5 | Book-step volume is absorbed by a few addresses | Immediacy for a seller who must sell regardless of price | the top 10 addresses take under half of it |
| C6 | Liquidation flow is less informed than ordinary taker flow | A margin call is about the account, not news | markouts against liquidation flow are no better for the rester than against ordinary taker flow of the same size, coin and volatility |
| C7 | The price still keeps moving against the absorber first | Liquidations cluster when a move began elsewhere, so the rester is often stale against other venues | absorber markouts are positive from the first second, with no early loss |
| C8 | Payment is for inventory risk, not speed | Makers pull quotes in cascades, so those who stay carry the risk | gross markout does not rise with cascade intensity |
| C9 | The backstop earns its forfeit on average and loses it in tails | It takes positions the book would not, at a guaranteed discount | backstop profit is not concentrated in few events, or its tails do not show up in HLP |

### Why larger players might leave anything

| # | claim | falsified if |
|---|---|---|
| C10 | **They leave nothing at the touch.** Fast makers take the best-priced fills | slow-resting orders at the touch earn the same as the fastest addresses |
| C11 | **They may leave something deep.** Risk limits thin the book in cascades, so deep levels clear at a discount | deep-level fills have markouts no better than the touch, net of fees |
| C12 | **What is left may be too small to matter to them,** or sit in coins they will not hold | large addresses fill as much in small coins and deep levels as anywhere |
| C13 | **The backstop itself is closed by design.** Its privilege is protocol-assigned, so no one competes for it, and an outsider shares it only by depositing in HLP | outside addresses receive `method: "backstop"` as liquidator |

**The likely weak point, stated first:** a slow participant can place a deep order, but cannot cancel it fast. So its
fills may arrive mainly when the price is really going through that level. C11 can look fine for fast makers and still
fail for us, so every markout for an outsider must assume a stated reaction delay, not the best address's speed.

## 3. Where an outsider could stand

| place | what it is | open question |
|---|---|---|
| **A. HLP deposit** | Passive share of all HLP's strategies, 4-day lock | The benchmark: if it clears the bar, a resting strategy must beat it to be worth anything. Not a pure liquidation return |
| **B. Pre-placed deep orders** | Resting bids or asks far from the touch, with a slow cancel | The only place this study can test as a new way to stand there |
| **C. Taking after the break** | Buying after a forced down-break | **#27, #32 and #45 already occupy this, and are frozen.** Not re-tested here |
| **D. Triggering liquidations** | Pushing the price into visible liquidation levels | **Excluded.** It looks like market manipulation and is a different business. Public addresses make liquidation levels visible, so measurement of others doing it may appear as information only |

## 4. Why the bar is demanding

$2,000 a year after $400 of costs needs **$2,400 a year gross, 48% on $5,000**. At 80 hours a week it is about $0.48 an
hour, so the time is effectively unpriced. Tell me if you want it priced.

Arithmetic, not an estimate of anything: a resting entry with a maker exit costs 3 bps at the base tier, and with a taker
exit 6 bps. **At 5 bps net per round trip, $2,400 needs $4.8M of round trips a year, about $13,000 a day,** or 2.6 times the
capital daily. At 20 bps net it needs about $3,300 a day. Forced flow would have to reach an order placed by someone slow
that often, on that many days, which is why capacity decides this before the average does. These net-edge figures are
illustrations, not findings.

## 5. Problems for the next steps

1. **Step 0 is incomplete.** S3 access needs an AWS account that you create and run (research/HL_ARCHIVE.md).
2. **Your own node doesn't fit the budget.** Hyperliquid asks for 16 vCPUs, 128 GB of RAM and 500 GB of SSD, in Tokyo for
   lowest latency, with about 100 GB of logs a day on default settings. Rented hardware of that size would very likely
   cost well over $400 a year; no quote was taken. **So this study assumes S3 only.** If the order-level history is
   missing from S3, the gate in step 2 may fail for that reason alone, unless the budget changes.
3. **Transfer cost may exceed the budget too.** Sizes are unknown until the listing. You will get a figure and a reply is
   needed before any download.
4. **A clean sample may hold no extreme event.** If order-level history starts in 2026-01 and stops before 2026-10-30, it
   excludes 2025-10-10. The tail table would rely on older fills, if they exist, and on secondary accounts.
5. **The cut-off stays.** Nothing dated 2026-10-30 or later is read. That includes `data/hlbook/` and the forward folders.

## 6. Not verified

- **All rules above:** documentation only, tested by C1–C4 if the data allows.
- **The Liquidator Vault:** the liquidation page names it as part of HLP, while the protocol-vault page says only that
  HLP "performs liquidations". Addresses and accounting are not established.
- **October 2025:** secondary sources put HLP's gain near $40M–$41.5M, and a Gauntlet paper's auto-deleveraging estimates
  ($660M simulated, $2.1B realised) are disputed by Hyperliquid's founder. Used only as a reason to study tails, never as
  data. No primary post-mortem was found.
- **C5–C13:** hypotheses. The author expects C10 to hold and is unsure of C11; neither has been measured.
- **Rules can change.** The rules were read once, on 2026-10-31, and this sample may span earlier versions. Rule history is
  not known.

## Sources

- [Liquidations](https://hyperliquid.gitbook.io/hyperliquid-docs/trading/liquidations), [Auto-deleveraging](https://hyperliquid.gitbook.io/hyperliquid-docs/trading/auto-deleveraging), [Funding](https://hyperliquid.gitbook.io/hyperliquid-docs/trading/funding), [Fees](https://hyperliquid.gitbook.io/hyperliquid-docs/trading/fees), [Protocol vaults](https://hyperliquid.gitbook.io/hyperliquid-docs/hypercore/vaults/protocol-vaults), [Websocket subscriptions](https://hyperliquid.gitbook.io/hyperliquid-docs/for-developers/api/websocket/subscriptions.md), [Historical data](https://hyperliquid.gitbook.io/hyperliquid-docs/historical-data)
- [Node requirements](https://github.com/hyperliquid-dex/node)
- Secondary: [CoinGecko on HLP](https://www.coingecko.com/learn/hyperliquid-hlp-vault-analysis), [Protos on the Gauntlet paper](https://protos.com/outdated-algorithm-caused-650m-excess-losses-on-hyperliquid-report), [Dwellir order statuses](https://www.dwellir.com/docs/hyperliquid/data-catalog/node-feeds/order-statuses)
