# Event Sourcing Ledger — API

FastAPI backend for a personal finance director built on event sourcing + CQRS principles.

## API Endpoints

| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/accounts` | Create a new account |
| GET | `/accounts` | List all accounts with balances |
| GET | `/accounts/:id` | Account detail + transaction history |
| POST | `/accounts/:id/events` | Append an event (deposit/withdraw) |
| GET | `/events` | Event timeline (all accounts) |
| POST | `/transfer` | Transfer between accounts |

## Database

PostgreSQL with a single append-only `events` table and a cached `account_balances` projection table.

```
events (
  id TEXT PRIMARY KEY,
  aggregate_id TEXT NOT NULL,
  event_type TEXT NOT NULL,
  data JSONB NOT NULL,
  version INT NOT NULL,
  created_at TIMESTAMPTZ NOT NULL
)
```
