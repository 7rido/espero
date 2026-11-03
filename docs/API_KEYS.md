# API keys: the policy, before any key can trade

**Written 2026-11-02.** Today the only key that signs anything is the Hyperliquid **testnet** key that
`espero/hl_exchange.py` reads, and no key in this repo can move real money. This is the policy every key follows
from now on, and the one a mainnet key would have to follow if the account holder ever lifts the no-mainnet rule
(research/DESIGN_MAINNET_PATH.md). The keys are the holder's: they create them, store them and revoke them. No
agent reads, prints, asks for or types a key (AGENTS.md).

## The rules

1. **Nothing in the repo.** Keys live in `.env` on the trading machine only: git-ignored, readable by its owner
   only (`chmod 600`), never committed, never printed. `.env.example` names every variable with no value.
   `tests/test_api_keys.py` fails if `.env` stops being ignored, if `.env.example` gains a value for a key, or if a
   tracked file holds a private key block.
2. **A separate account for the bot.** Each venue gets a sub-account (or, on Hyperliquid, a separate main account)
   holding only the capital allocated in docs/HOLDER_INPUTS.md. The holder's other funds are never reachable from
   the bot's key. A venue failure then costs at most that sub-account, inside research/RISK_POLICY.md's per-venue cap.
3. **Withdrawals disabled** on every key that can trade, at the venue, not just in our code. A key that could withdraw
   is refused.
4. **Read-only wherever reading is enough.** Reconciliation and attribution read fills, positions and statements:
   Hyperliquid's are public by address and need no key at all; an exchange's need a read-only key with trading and
   withdrawals disabled (research/VENUE_NONUS.md, "Reconciliation").
5. **An IP allow-list** on every trading key: the trading machine's address only. A home connection whose address
   changes needs a fixed way out (a static address from the provider, or a VPN with a fixed exit) before a mainnet key
   is created.
6. **Hyperliquid: an API (agent) wallet.** It signs orders for the account and cannot withdraw. The account's own
   wallet key never sits on the trading machine. `HL_WALLET_ADDRESS` names the account; `HL_PRIVATE_KEY` is the agent
   wallet's.
7. **The narrowest scope:** futures trading on the named account; no transfers, no sub-account creation, no
   options or margin products the sizing document does not name.
8. **Testnet and mainnet never share a key, a wallet or a `.env` value.** `hl_exchange.guard` refuses anything that
   is not the testnet; a mainnet module would refuse a testnet key the same way.
9. **Rotation:** every 90 days, and at once after any doubt (a lost machine, a leaked log, a departed helper).
   Revocation is at the venue first, then `.env`.
10. **The trading machine:** FileVault on, a login password, automatic updates applied by hand at a quiet hour (an
    update restarts the machine: the recovery drill in docs/RUNBOOK.md is what happens then), and no remote access
    that skips the login.

## What the code holds today

- `hl_exchange.guard`: `HL_NETWORK=testnet`, `ESPERO_ALLOW_HL_TESTNET=1`, a testnet `HL_API_URL` if any, and only then
  `HL_PRIVATE_KEY`, read in that module and nowhere else.
- `broker.load_env`: loads `.env` without printing values; its warnings show line numbers only.
- `notify.redact`: a webhook URL is a bearer secret and is never logged whole.
- `approvals.secret`: the operator's TOTP secret is read from the environment and never printed or journaled.
- CI holds no key, and every test runs with none.

## Revoking, in an emergency

1. At the venue: delete the key (or the agent wallet's approval on Hyperliquid).
2. On the trading machine: remove the line from `.env`, and create the executor's `.stop` file or the state folder's
   `KILL` file so nothing tries to trade on the next loop.
3. Reconcile: `espero.reconcile.startup` against the venue's own record before anything trades again.
