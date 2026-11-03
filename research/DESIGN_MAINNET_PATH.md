# The mainnet order module: the design it was built from

**Built 2026-11-03 as `espero/hl_mainnet.py`, after the account holder lifted the no-mainnet rule in writing, in
their own words, in signed commits (research/MAINNET_LIFT.md, cf109df and 88cd069).** The guards below are the
module's, in this order, and `tests/test_hl_mainnet.py` refuses on each one alone. Nothing below was changed to build
it. **This was a design document, written 2026-11-02, when there was no mainnet order path in this repo, and the
page added none.** AGENTS.md: "There is no mainnet order path in this repo, and none is to be added", and
`espero/hl_exchange.py` signs on Hyperliquid's testnet only. The module described here becomes code only after the
account holder lifts that rule **in writing, in their own words, in a committed document**
(docs/HOLDER_INPUTS.md, `mainnet_lift`). Nothing is prepared for it quietly, no guard is weakened, and an agent does
not write the lift. `tests/test_no_mainnet.py` fails if any module other than `hl_exchange.py` imports the signing
SDK or builds its `Exchange`, or if `hl_exchange.py` stops being testnet-only.

It is designed now, before any verdict, so that the guards are fixed by reasoning rather than by a pass that
someone is eager to trade.

## The interface: the same as `TestnetExchange`

A `MainnetExchange` would offer exactly `hl_exchange.TestnetExchange`'s methods, so every executor, test and
replay written against the testnet works unchanged: `limit(coin, side, size, price, tif, reduce_only, cloid)`,
`order_status(cloid)`, `book(coin)`, `cancel(coin, oid)`, `open_orders()`, `fills(since_ts)`, `positions()`. It
would add two the kill switch needs: `cancel_all()` and `flatten(tranche_slips)`. Rounding (`round_size`,
`round_price`) and response parsing (`parse_order_response`) are shared, not copied.

## The guards, in the order they are checked, every time the exchange is built

Each refusal raises `MainnetRefused`, never caught inside the module, as `TestnetRefused` is today.

1. **`HL_NETWORK` is `mainnet`.** The testnet module refuses anything else, and this one refuses anything but
   mainnet, so the two can never be built from the same environment.
2. **`ESPERO_ALLOW_HL_MAINNET=1`**, a second, explicit opt-in, distinct from the testnet's flag.
3. **The holder's lift is committed and signed.** `docs/HOLDER_INPUTS.md`'s `mainnet_lift` names a document. The
   module checks that:
   - the file exists at `HEAD` (`git cat-file -e HEAD:<path>`), and the working tree's copy equals `HEAD`'s, so an
     uncommitted edit counts for nothing;
   - the commit that last changed it, and the commit that last changed the allow-list (guard 4), pass
     `git verify-commit` against an allowed-signers file **kept on the trading machine outside the repo**, holding
     only the holder's public key. The holder's private signing key sits in a hardware key or an agent that asks for
     a touch, so nothing running on the machine can sign as the holder. A lift whose signature does not verify is
     refused, however it reads;
   - the lift's own answers block (machine-readable, like docs/HOLDER_INPUTS.md's) names the venue, the coins, the
     largest order and the largest position in dollars, and an **expiry date**. Past it, the lift has lapsed.
4. **An allow-list,** `config/mainnet_allowlist.json`, committed in a commit the holder signed: rows of (venue, coin,
   largest order notional, largest position notional). Every order is checked against it; a coin or size not on it is
   refused, whatever the rule asks.
5. **A ruling from the risk gate:** every order carries a `risk.Ruling` with `allowed`, and its `policy_hash` must
   equal `risk.policy_hash()` of the policy committed at `HEAD` (research/RISK_POLICY.md). The capital behind it is
   `holder.allocated_usd()`, which is 0 until answered.
6. **The key on the trading machine only.** `HL_MAINNET_PRIVATE_KEY` is read here and nowhere else, only after guards 1
   to 5 pass. It is a Hyperliquid API (agent) wallet that cannot withdraw (docs/API_KEYS.md). The module refuses when
   `CI` is set, and when the machine is not the one the lift names (a hash of its hardware identifier, written in the
   lift).
7. **The base URL is a constant**, asserted after the SDK is built: the environment can refuse, never redirect.

## Dry run is the default

`MainnetExchange(dry_run=True)` is what an executor gets unless it asks otherwise. It runs guards 1 to 5 and the
allow-list, then **journals the exact order it would have sent** (coin, side, size, price, time in force, client order
id, the ruling's policy hash, the lift's commit) to `state/mainnet-dryrun.db`, and returns a result marked `dry`. It
reads no key and opens no connection that can sign. Live mode needs `dry_run=False` and every guard. A sleeve's
canary (research/DEPLOYMENT_LADDER.md, rung 2) is preceded by its dry run on the same days as its testnet rung, so
the two journals can be compared order by order.

## The kill switch: what it does to open positions and resting orders

Two levels, both files in the state folder, read before every order and on every loop:

| file | resting entry orders | resting exit orders | open positions | new entries |
|---|---|---|---|---|
| `KILL` (any content) | cancelled at once | kept | run to their registered exits | none |
| `KILL` reading `flatten` | cancelled | cancelled | **flattened**: reduce-only IOC orders, perp legs first, in tranches that cross further on each unfilled try (50, 200, 500, then 1,000 bps, as `hlp_testnet.EXIT_SLIPS`), retried until flat | none |

While either file exists the module sends nothing that is not reduce-only. A venue that does not answer during a
flatten is retried with backoff and the operator is called (`notify`, `espero watchdog`). An executor's own `.stop`
file is the first level for that executor alone. The risk gate's week stop and the holder's own stop flatten the same
way (research/RISK_POLICY.md).

## Around the module

- **Startup reconciliation** (`espero.reconcile.startup`) before the first order after any start: a break refuses
  every entry until it is resolved.
- **Daily equity reconciliation** (`espero.attribution.check_equity`) against the venue's own record: a break pauses
  the sleeve.
- **Exchange-side stops** for a rule with a stop: placed on the venue, so the stop survives the machine.
- **The clock** (`watchdog.clock_ok`): no order on a clock more than a second off.
- **Every order, ruling, dry run, fill and refusal** journaled, with the lift's commit and the policy's hash.

## The tests it would need, before it could sign anything

Every guard's refusal, one by one, as `tests/test_hl_exchange.py` does for the testnet; the signature check against a
test key in a temporary repo, including an unsigned lift, a lift signed by another key, an edited-but-uncommitted lift
and a lapsed one; dry run never building a signer; allow-list refusals; the kill switch's sequence on a fake exchange;
the base URL assertion; and a replay of its testnet rung's days (`espero/replay_stack.py`) through the dry run.

## What this page does not do

It does not lift the rule, propose that it be lifted, or make it easier to lift. It writes no code that can sign on
mainnet, and the test beside it keeps it that way until the holder decides otherwise, in their own words.
