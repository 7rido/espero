# The operator's protocol: who answers, how, how fast, and what happens when nobody does

**Written 2026-11-02, before any sleeve exists.** Nothing here places an order by itself. The account holder lifted
the no-mainnet rule in writing on 2026-11-03 (research/MAINNET_LIFT.md) for a plumbing canary on rule 8, so
`espero/hl_mainnet.py` exists behind research/DESIGN_MAINNET_PATH.md's guards; every other sleeve still waits for a
forward rule to pass and its sizing document to be written. This is the protocol that will
stand between a passed rule and its orders, fixed while no verdict can shape it. `espero/approvals.py` is its
code and `tests/test_approvals.py` holds it.

## Who the operator is

The operator is the account holder (research/VENUE_NONUS.md: "The operator is the holder"), on their own
machine, with their own keys. Another person answering for them would be another person trading on the venue,
and this protocol does not cover that.

## Which rules may wait for a person

research/LIVE_LATENCY.md gives every rule a latency budget and a class, derived from numbers and not chosen:

| class | who acts | proposals? |
|---|---|---|
| **operator-paced** (#4, #8, #12, #63) | the operator approves, or the proposal lapses | yes, mode A |
| **live-from-tape** (#24, #29, #31, #34, #58, #59, #60, #64, #65) | the machine, unattended, within the risk gate, or no one | never: **auto-only** |
| **next-day-batch** (#22, #23, #38) | no one: its inputs arrive later than its budget | never |
| **not tradable live** | no one | never |

**The rule:** a rule whose budget is shorter than the operator's response time is auto-only or not traded, never
operator-paced. The response time is **4 hours** (`espero.latency.OPERATOR_RESPONSE_S`): a person who checks a few
times a day answers in that time, or not at all. The holder's answer in docs/HOLDER_INPUTS.md may raise it, which
can only move rules out of operator pacing. An auto-only rule runs unattended only after the holder's separate,
written decision to allow it (docs/HOLDER_INPUTS.md); until then it is not traded.

## The two modes

**Mode A, the machine proposes and the operator approves.** For an operator-paced rule's entry, the machine sends
a proposal and waits. The operator approves it, rejects it, or sizes it down. Nothing is sent without an
authenticated approval; silence means no entry.

**Mode B, the operator proposes and the machine checks.** The operator asks for one of two things:

- **an entry that follows a live event of a registered rule:** same rule, coin and side, still inside the rule's
  budget, at no more than the risk gate's size. An entry that no registered rule's live event supports is refused.
  There is no path from "this looks good" to an order that skips a numbered pre-registration (docs/HOW_IT_WORKS.md);
- **an early exit** from an open position, which only reduces risk and is always accepted with a code and a reason.

**Exits never wait.** The rule's own exit is executed when it falls due, with no proposal; the operator may exit
earlier, never later. Risk stops (research/RISK_POLICY.md) and edgewatch's actions (#70) never wait for an answer.

## What a proposal says

`approvals.Proposal`: an id; the rule (test number) and sleeve; the coin and side; the size **from the risk gate**
(`risk.check`, never more); the decision price; the registered round-trip cost from `espero.costs`; the stop, where
the rule has one; the rule's latency class; when it was made and when it lapses; the rule's signal time. Its
SHA-256 digest is recorded with it, so a proposal changed after it was recorded is refused rather than approved.

## The channels

- **Out:** the home screen (`espero ui`, "Approvals") lists pending proposals; `notify.py` sends each one to the
  macOS notification centre and, when `ESPERO_WEBHOOK_URL` is set, to the webhook. The webhook carries proposals
  out only: nothing arrives through it.
- **In:** a reply is a file in `state/approvals.inbox/`, written by `espero approve ID ANSWER CODE` or by the home
  screen, and consumed by the sleeve runner, which journals it. A reply from elsewhere is any way of running
  `espero approve` on the trading machine, and it still needs the code.

## Authentication: a one-time code per reply

- **The code** is a 6-digit TOTP (RFC 6238, SHA-1, 30-second steps), the kind any authenticator app shows.
- **The secret** is created by the holder and kept under the environment name `ESPERO_OPERATOR_TOTP` in `.env` on
  the trading machine, and in the holder's authenticator app. The repo never prints, logs or journals it, and no
  agent sees it. Set-up is the holder's act: generate 20 random bytes, base32 them, add them to the app and to
  `.env`.
- **What counts:** a code for the current 30-second step or the one before it, used once. A code spent on one
  reply cannot answer another. The code itself is never written to the journal.
- **What does not count:** a reply with no code, a wrong or reused code, a reply to an unknown, closed or lapsed
  proposal, an override without a reason, a "modify" that sizes up. Each is journaled as `refused` with its reason.
  An unauthenticated reply counts as silence: the proposal stays open until it lapses or a valid reply arrives.

## How long a proposal waits, and what silence does

| class | waits | silence on an entry | silence on an exit |
|---|---|---|---|
| operator-paced | its budget, less the feed's delay and 5 minutes to place and fill, at most 24 hours (`approvals.wait_s`) | **not taken**, journaled `silence` | none: exits never wait |
| live-from-tape | not proposed | — | — |
| next-day-batch, not tradable | not proposed | — | — |

Waits today: #12 about 8 hours, #8 about 7.3 hours, #63 about 23.4 hours, #4 the 24-hour cap. A silent entry is a trade the
paper twin takes and the live sleeve does not: the live sleeve then trades a subsample of its registered events,
and #69 reports what silence cost.

## Every answer is an event

`approval_events`, in `state/approvals.db`: `proposed`, `approved`, `rejected`, `modified`, `exit`, `operator`,
`silence` and `refused`, each with its time, its proposal, the reply without its code, and a reason. The table is
**append-only** (SQLite triggers refuse an UPDATE or DELETE) and **hash-chained**: each row's SHA-256 covers the row
before it, so a row changed or removed behind the table's back shows in `Ledger.verify`.

An **override** is any answer other than "approve as proposed": a rejection, a smaller size, an early exit, a late
approval, an operator's own entry, and silence. An override needs a written reason, except silence, whose reason
is the lapse.

## Operator alpha: what the overrides earned (#69)

research/PREREGISTRATION_OPALPHA.md, information only: each override is scored against the paper twin's trade on
the same event, both net of costs, and the result is reported once, at 30 comparable overrides or a year after the first
live proposal. It decides nothing by itself.

## For an auto-only rule

The operator does not pace it. They watch it (`espero watchdog`, the home screen), stop it (the `KILL` file and
each executor's `.stop` file), and answer what the machine cannot settle alone: an edgewatch alarm (#70), a risk
stop's acknowledgement (research/RISK_POLICY.md), a reconciliation break (`espero.reconcile.startup`).

## What is not built

- No inbound network listener: replies arrive only as files on the trading machine.
- No mainnet order path, and nothing here can create one.
- No sleeve runner yet: it is built with the first sizing document, and it consumes the inbox as described here.
