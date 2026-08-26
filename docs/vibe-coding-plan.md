# Building This With AI (Vibe Coding) — Plan

How to use AI tools to build this platform fast without blowing up on the
money-handling parts. Vibe coding (fast, low-review, "just let the AI build
it") is great for most of this project, and dangerous for the part that
touches real money, order placement, or risk limits — a bug in the dashboard
is annoying, a bug in `place_order()` or `check_daily_loss_limit()` can lose
real money in seconds. Work is split into 🟢 vibe-fast zones and 🔴/🟡
go-slow-review-everything zones; don't treat them the same.

## Phase 1 — Skeleton & Setup — 🟢 Full Vibe Mode
FastAPI + PostgreSQL backend, React/Next.js frontend, monorepo. DB tables:
users, broker_credentials, strategies, orders, positions, price_history,
risk_limits, audit_log. Redis for caching. Basic auth. **Status: done** —
see `backend/app` and `frontend/`.

## Phase 2 — Broker Connection — 🟡 Vibe, Then Review Carefully
Broker connector behind a swappable interface (OAuth login, token refresh,
balance/holdings/live prices via WebSocket). Test against the broker's real
sandbox — don't trust "no errors" as correctness. **Status: not started** —
broker is undecided; `app/services/` is the placeholder for this.

## Phase 3 — Price Data & Storage — 🟡 (bumped up from 🟢)
Save incoming ticks to TimescaleDB, serve historical data for backtesting,
stream live prices to the frontend over WebSocket. Must include: reconnect
on drop, staleness detection (a strategy must not act on a price older than
a defined threshold), and a defined behavior for "feed is down" — a silently
stale price feeding a live strategy is a real-money bug, not a dashboard bug.

## Phase 4 — The Strategy Brain — 🟡 Vibe the Structure, Review the Logic
AI builds the `on_price_update()` scaffolding and backtesting engine
(Sharpe ratio, max drawdown, win rate). The actual trading rules come from
the trader, not from the AI guessing what's profitable. Explicitly check
backtests for lookahead bias — a suspiciously perfect result is usually a
bug, not a great strategy.

## Phase 5 — Order Placement & Risk Controls — 🔴 Slow Mode, Review Every Line
This is where vibe coding stops. AI writes a first draft; a human reads every
line, and the AI explains its own code back function by function. Required
properties, not optional:

- **Idempotent `place_order()`** — the same idempotency key called twice
  must never create two orders (enforced at the DB level via a unique
  constraint, not just application logic — see `orders.idempotency_key`).
- **Fail-closed `check_risk_before_order()`** — if the risk check itself
  errors, times out, or can't reach its data store, the order is blocked,
  not allowed through. This is the most common way risk gates get silently
  bypassed.
- **Atomic risk-state updates** — checking/updating cumulative daily loss or
  position size under concurrent order attempts needs a DB lock or atomic
  operation (`SELECT ... FOR UPDATE` or equivalent), not a naive
  read-check-write, or two near-simultaneous orders can jointly blow past a
  limit that either alone would have respected.
- **Account-wide aggregation** — if more than one strategy can be live at
  once, risk limits must be enforced across all of a user's strategies
  combined (see `risk_limits.strategy_id` being nullable = account-wide row),
  not just per-strategy.
- **Broker rate limiting** — a rate limiter in front of order placement so a
  strategy bug can't burst past the broker's orders/sec ceiling.
- **`kill_switch()`** — cancels all pending orders and disables all
  strategies immediately; test it under a broker-API-down condition too, not
  just the happy path.
- **Correlation-ID logging** — every order attempt logs signal → risk check
  → broker call → fill confirmation under one correlation ID in `audit_log`,
  so any outcome can be reconstructed after the fact.

Nothing here goes near real money until it has run in paper trading against
concrete exit criteria (see checklist below), not just "for a few weeks."

## Phase 6 — Dashboard — 🟢 Full Vibe Mode
Live positions, P&L, order history, a prominent stop-all-trading button,
WebSocket live updates, alert notifications on risk-limit breaches.

## Phase 7 — Compliance Tagging — 🟡 Vibe, Then Verify Against Current Broker Docs
Algo-ID/Strategy-ID tagging is broker-specific and regulatory detail changes
over time — always verify the current required format against the specific
broker's live API docs rather than trusting any cached assumption about it,
including this document's.

## Prompting Tips
- Give the AI the full DB schema and function list early so it understands
  the whole system, not just the open file.
- One function or feature per prompt in the 🔴 zone — review before moving on.
- Ask for tests alongside the code, especially edge cases, for order/risk logic.
- For 🔴-zone work, explicitly say the code handles real money and ask it to
  reason about duplicate execution, race conditions, and silent failures.
- After any change to order/risk code, get a plain-English summary of what
  changed — don't just trust the diff.

## Checklist Before Any Real Money
- [ ] Paper trading passed a **quantitative** bar, not just elapsed time:
      minimum N trades, zero unhandled exceptions, zero risk-limit breaches
      that weren't correctly blocked, a survived simulated broker-disconnect,
      a survived simulated duplicate-order call, and exact PnL reconciliation
      against the broker statement.
- [ ] Every order-placement and risk-check function read line-by-line by a
      human, not just AI-reviewed.
- [ ] Tested: broker disconnect mid-order, duplicate order request, hitting
      the daily loss limit, hitting the order-rate limit, and the risk-check
      function itself throwing an error.
- [ ] Kill switch tested and confirmed it stops everything, including when
      the broker API is unreachable.
- [ ] First real-money stage is narrow and explicit: one strategy, one
      instrument, minimum lot size, for a defined trial period — before
      scaling to the full strategy/instrument universe.

## Secrets
Broker API keys, secrets, and tokens are stored encrypted, never plaintext,
never committed, and never pasted into an AI chat/prompt. During all
AI-assisted development, only a paper-trading/sandbox broker account is
connected — never a live-money connection.
