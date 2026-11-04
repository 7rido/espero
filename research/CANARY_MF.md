# Rule 8's plumbing canary: the sleeve `mf-canary`

**Written 2026-11-03, before the canary's first testnet order.** This is the sleeve's document for the deployment
ladder (research/DEPLOYMENT_LADDER.md). It stands in for the sizing document of research/TEMPLATE_SIZING.md, which a
verdict would need: **there is no verdict.** Rule 8 is a forward test judged once, after 2027-05-03
(research/FORWARD_MF.md), and nothing here reads its running numbers or changes it. The canary exists because the
account holder lifted the no-mainnet rule in writing for exactly this, in signed commits (research/MAINNET_LIFT.md,
cf109df and 88cd069), and signed the allow-list and this sleeve's testnet bar (5d58557). It proves the order path,
not the edge. **P&L is never a reason to keep it, grow it or stop it.**

## What it trades

- **The rule:** #8 as frozen, `espero.mf.decide`: decided at Sunday's close, on Hyperliquid's own daily bars (the
  shadow book `mf-hl`'s prices), the turnover buffer fed the shadow book's holdings, so the canary's picks are the
  shadow book's picks. Every week the canary journals both and any disagreement, as information.
- **Each leg at a fixed small size, not the rule's weights:** an entry is a buy of $12 (Hyperliquid's $10 minimum
  with room for rounding), an exit sells what the canary itself bought. Rule 8 is long-only.
- **Rung 1, the testnet:** every coin rule 8 picks that the testnet lists, on the testnet account in `.env`.
  **Rung 2, mainnet:** only the lift's and the allow-list's coins (BTC, ETH, SOL, ETC, NEAR, BCH), at the venue's
  minimum, through `espero/hl_mainnet.py`. BCH is not listed on the testnet, so it is never traded on rung 1.

## Who acts, and when

- **Entries wait for the holder's yes.** Each is a proposal in `state/approvals.db` (docs/OPERATOR.md), answered with
  `espero approve <id> approve <code>` or on the home screen, with the one-time code. Rule 8 is operator-paced
  (research/LIVE_LATENCY.md): its budget is 8.4 hours from Monday 00:00 UTC. The canary decides once the Sunday bar
  is complete, and a proposal lapses at Monday 00:00 UTC plus the budget less the five-minute execution allowance,
  about 08:19 UTC. **Silence is "no"**: the entry is not taken, the ledger says so, and #69 scores it.
- **A decision made after that time is journaled `late` and proposes nothing.** The Mac may be asleep at Monday
  00:00 UTC; the canary does not catch up.
- **One code, one answer.** A one-time code answers a single proposal, so a second proposal in the same week is
  answered once the authenticator shows the next code, 30 seconds later. A reused code is refused and counts as
  silence until a valid answer arrives.
- **Exits never wait** (docs/OPERATOR.md): a coin rule 8 drops is sold at once.
- **Every proposal is announced** through `espero.notify`: the notification centre, and the webhook when the holder
  sets one.

## The account it shares

The testnet account is also #59's (`hlp2-testnet`). So the canary **never reads the venue's position totals as its
own** and **never cancels or flattens the whole account**. Every canary order carries a client id derived from
`espero-mfcanary`, the week, the coin and the leg; its holdings, exit sizes and round trips come from its own journal
(`state/mf-canary.db`), matched against the venue's fills by order id.

carry-maker's mirror trades the same account with a short perp leg, and Hyperliquid nets one position per coin per
account, so a reduce-only sell can be refused when the account is net short. **The canary's testnet exits are plain IOC
sells of exactly its own size**, as #59's executor's are (docs/RUNBOOK.md). On mainnet the account is the canary's
alone, so the mainnet module's reduce-only orders apply there.

## The risk gate

Every entry passes `risk.check`. On the testnet the gate sizes against the testnet's play capital
(`mf_canary.TESTNET_CAPITAL`, $1,000), because the holder's $50 at the policy's 20 % per coin and 50 % per venue
allows two $12 positions and the rung could never count its round trips. **Beside it, the journal records the ruling
the holder's own capital would have given**, so rung 2's limits are visible before it starts. On mainnet the gate
uses the holder's capital only.

## Rung 1 passes, for this sleeve, when

1. **10 round trips** (`rungs.testnet_round_trips("mf-canary")`, the holder's signed amendment), each an entry and
   its exit both filled and both **matched to the venue's fills by order id** (`espero.reconcile`), with no break;
2. every fault in `espero/replay_stack.py` drilled, as the ladder requires;
3. the kill switch drilled: `state/mf-canary.stop` stops entries and sells everything the canary holds;
4. placement inside the budget at the 95th percentile;
5. a restart during an open trade sends no duplicate order: an order with no answer is looked up by its client id
   before anything is resent.

## Rung 2 and the dry run

Rung 2 runs `espero/hl_mainnet.py` in a process the holder starts with `HL_NETWORK=mainnet` and
`ESPERO_ALLOW_HL_MAINNET=1`; the testnet and mainnet environments are kept apart on purpose, so this runner never
fakes the mainnet environment. Its dry run is replayed from this sleeve's journal: every testnet leg records its
decision price, size and both rulings, so the mainnet dry run can be compared to the testnet rung order by order
before the first real order.

## What stops it

`state/mf-canary.stop` (no entries, sell what the canary holds); the state folder's `KILL` file; the lift's expiry,
2027-01-31; a reconciliation break, which refuses entries until it is resolved; the holder's drawdown stop on rung 2.

## Amendment 2026-11-04, by the account holder: a day to answer

Before the canary's first proposal. This sleeve's entries may be approved until Monday 23:55 UTC (6:55 p.m. Eastern in
winter), a day less the five-minute execution allowance, instead of rule 8's budget of 8.4 hours, which closed at about
08:19 UTC (3:19 a.m. Eastern), before my Monday morning. Proposals still appear just after Monday 00:00 UTC. A buy may
land up to a day after rule 8's decision. The canary proves the order path, not the edge, so it waits for me. For this
sleeve only, the testnet stage's latency criterion is measured from my approval to the venue's acknowledgement, not
from the signal. Everything else above stands. The timestamp beside this file covers the text before this amendment.
