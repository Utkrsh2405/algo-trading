# Algo Trading Platform

Monorepo: FastAPI backend + PostgreSQL (TimescaleDB) + Redis, Next.js frontend.

**Risk guidance lives in [`docs/vibe-coding-plan.md`](docs/vibe-coding-plan.md)** — read it before
touching anything under `app/services/order*`, `app/services/risk*`, or any broker path.

## Architecture

```
frontend/               Next.js 14 dashboard (live prices, orders, kill switch)
backend/
  app/
    api/routes/         auth, prices, orders, broker (OAuth callback)
    models/             users, orders, positions, risk_limits, audit_log, …
    services/
      broker/           BrokerInterface → ZerodhaBroker | MockBroker
      order.py          place_order() + kill_switch() — 🔴 safety-critical
      risk.py           check_risk_before_order() — fail-closed, SELECT FOR UPDATE
      rate_limiter.py   Redis token-bucket (atomic Lua)
      price_feed.py     WebSocket feed with staleness watchdog
      strategy_engine.py  BaseStrategy + StrategyEngine scaffolding
```

## Prerequisites

- Python 3.11+
- Node.js 20+
- Docker Desktop (for Postgres + Redis)

## Backend Setup

```bash
cd backend
python -m venv .venv
.venv\Scripts\activate        # Windows
pip install -r requirements.txt
copy .env.example .env        # then edit values
```

Start Postgres + Redis:

```bash
docker compose up -d
```

Run migrations:

```bash
cd backend
alembic revision --autogenerate -m "initial tables"
alembic upgrade head
```

Start the API:

```bash
uvicorn app.main:app --reload
```

API docs: http://localhost:8000/docs

## Frontend Setup

```bash
cd frontend
npm install
copy .env.local.example .env.local
npm run dev
```

Dashboard: http://localhost:3000  
Login page: http://localhost:3000/login

## Zerodha Broker Setup (Phase 2)

1. Set `KITE_API_KEY` and `KITE_API_SECRET` in `backend/.env`.
2. Navigate to http://localhost:8000/api/broker/login in your browser.
3. Complete the Zerodha OAuth flow. The callback auto-starts the live price feed.

Without these keys the platform uses the in-process `MockBroker` (paper trading).

## SEBI Compliance Tagging (Phase 7)

Set `KITE_ALGO_TAG` in `backend/.env` to your registered algo identifier.

> ⚠ **Verify the required format** against the current Kite Connect API docs and the
> applicable SEBI circular **before going live**. Regulatory requirements change
> over time and this README may lag behind them.

## API Endpoints

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/api/auth/signup` | Register a new account |
| `POST` | `/api/auth/login` | Sign in, returns JWT |
| `GET` | `/api/auth/me` | Current user |
| `GET` | `/api/health` | Health check |
| `GET` | `/api/prices/{symbol}/history` | Historical price bars |
| `WS` | `/api/prices/ws` | Live price WebSocket |
| `GET` | `/api/broker/login` | Redirect to Zerodha OAuth |
| `GET` | `/api/broker/callback` | Zerodha OAuth callback |
| `POST` | `/api/orders` | Place an order (risk-checked, idempotent) |
| `GET` | `/api/orders` | List orders |
| `GET` | `/api/orders/{id}` | Get one order |
| `POST` | `/api/orders/kill-switch` | 🔴 Halt all trading immediately |
| `DELETE` | `/api/orders/kill-switch` | Re-enable trading |

## Alembic Migrations

After any model change, generate and apply:

```bash
cd backend
alembic revision --autogenerate -m "describe change"
alembic upgrade head
```

## Status

| Phase | Description | Status |
|-------|-------------|--------|
| 1 | Skeleton: auth, DB models, Redis, basic dashboard | ✅ Done |
| 2 | Zerodha Kite Connect broker integration | ✅ Done |
| 3 | Price feed robustness: staleness + watchdog | ✅ Done |
| 4 | Strategy Brain scaffolding | ✅ Done |
| 5 | Order placement & risk controls 🔴 | ✅ Done |
| 6 | Dashboard: live prices, orders, kill switch UI | ✅ Done |
| 7 | SEBI compliance tagging (Zerodha `tag` field) | ✅ Done |

## Before Real Money

See the full checklist in [`docs/vibe-coding-plan.md`](docs/vibe-coding-plan.md).  
**No live account should be connected until every item on that checklist is cleared.**

## Secrets

Broker API keys and tokens are never committed, never plaintext, never pasted
into an AI chat. Only a sandbox/paper account during all AI-assisted development.
