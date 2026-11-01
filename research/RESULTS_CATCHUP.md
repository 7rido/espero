# Results — how much of Hyperliquid's catch-up to Binance is left after a delay? (#57)

**NOT CAPTURED. At a 1,000 ms delay, a $1,000 market order held 30 seconds lost 8.02 bps per event after costs (95% CI −8.78
to −7.20).** All six coins and both halves are negative, and no delay measured has a positive mean, including 100 ms. The
catch-up stays a way of reading the market, and nothing more is done with it on this account. As registered, no test on unread
days follows.

Registered in `0cd35aa`; run once, with the code unchanged. Raw output: [catchup_output.txt](catchup_output.txt).

## The main case

| part | mean bps per event |
|---|---|
| Gross move, mid to mid, entry to exit | +3.39 |
| Walking the book, both legs | −2.41 |
| Fees, both legs | −9.00 |
| **Net** | **−8.02** |

| coin | gross | walk | net |
|---|---|---|---|
| BTC | 2.94 | 1.14 | −7.21 |
| ETH | 3.72 | 1.38 | −6.66 |
| SOL | 3.26 | 1.87 | −7.61 |
| XRP | 2.87 | 2.27 | −8.40 |
| DOGE | 3.90 | 2.82 | −7.91 |
| LINK | 3.28 | 3.61 | −9.32 |

Halves: −6.91 and −9.13. 11,136 events on 24 days: 97.5% filled, 2.4% unfillable, 0.1% without a snapshot.

## By delay, $1,000 and 30 s

| delay | net bps (95% CI) |
|---|---|
| 100 ms | −1.92 (−2.62 to −1.20) |
| 250 ms | −2.84 (−3.62 to −2.05) |
| 500 ms | −4.75 (−5.63 to −3.82) |
| **1,000 ms** | **−8.02 (−8.78 to −7.20)** |
| 2,000 ms | −9.77 (−10.25 to −9.27) |
| 5,000 ms | −10.46 (−10.88 to −10.06) |

**The shortest delays are blurred.** Fills wait for the next snapshot, about 0.54 s apart, so "100 ms" really means up to about
0.6 s. This sample can't say what a truly sub-100 ms order would see, and this account's measured path is about 0.9 s.

## Other cases, at 1,000 ms

| case | net bps (95% CI) | unfillable |
|---|---|---|
| $10,000, 30 s | −9.23 (−9.99 to −8.43) | 21.5% |
| $1,000, 5 s | −8.00 (−8.68 to −7.26) | 2.2% |
| $1,000, 60 s | −8.29 (−9.02 to −7.49) | 2.3% |

By entry, the mid had already moved the event's full size on 11.1% of events.

## Where the author's forecast was wrong

The registration expected a loss of 3–5 bps, and about 200 events a day. **The loss was 8.02 bps, with about 464 events a day.**
It estimated about 6.4 bps of move left after one second. This test found 3.39 at its 1,000 ms delay. The two differ: this event
rule fires live at any trade rather than on fixed bins, so it catches more and smaller moves, and fills wait for the next
snapshot. Which of those accounts for how much wasn't separated.

## What this doesn't show

- **It doesn't overturn #52.** Binance still moves first, and Hyperliquid still catches up. What fails is capturing that at this
  account's speed, through a taker order, after fees.
- **Not other ways of trading it.** Resting orders, lower fee tiers and much faster paths weren't tested. #39's work on resting
  orders found adverse selection, and they'd be a new test.
- **Calm days only.** These days were already read by #52, and they include no known cascade. A loss this consistent doesn't need
  a clean sample to be believed, and the sample's flaws would be expected to flatter the result, not hurt it.
- **It charges the displayed book as if nobody else reacts**, so a real order would probably do no better.

Not investment advice, and nothing here places an order. Plain summary: [OPERATOR_READOUT.md](OPERATOR_READOUT.md).
