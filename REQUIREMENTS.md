# Event Sourcing Ledger — Backend Specification

> **Author:** Engineering
> **Status:** Draft
> **Priority:** P0 (Core Infrastructure)

---

## 1. Overview

A personal finance director built on **event sourcing + CQRS**. Every financial action
(deposit, withdraw, transfer) is stored as a permanent, append-only event. Balances are
calculated by replaying events — never by updating a mutable balance column.

### Core Principles

1. **Append-only** — No updates or deletes on the events table. Ever.
2. **Replayable** — Any account balance at any point in time.
3. **Auditable** — Full provenance: who did what, when, in what order.
4. **Projected** — Read models are cached projections, not source of truth.

---

## 2. Tech Stack

| Component     | Technology         | Version  |
|---------------|--------------------|----------|
| Framework     | FastAPI            | 0.115+   |
| Python        | CPython            | 3.12+    |
| Database      | PostgreSQL         | 16+      |
| Cache / Tokens| Redis              | 7+       |
| ORM           | SQLAlchemy (async) | 2.0+     |
| Migrations    | Alembic            | 1.13+    |
| Auth          | JWT + Argon2       | PyJWT    |
| Testing       | pytest + httpx     | —        |
| CI            | GitHub Actions     | —        |
| Orchestration | process-compose    | —        |

---

## 3. Database Schema

### 3.1 `events` (Append-Only Store)

```sql
CREATE TABLE events (
    id           UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    aggregate_id TEXT NOT NULL,
    event_type   TEXT NOT NULL,
    data         JSONB NOT NULL,
    version      INT NOT NULL,
    created_at   TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX idx_events_aggregate ON events(aggregate_id, version);
CREATE INDEX idx_events_type ON events(event_type);
CREATE INDEX idx_events_created ON events(created_at DESC);
```

**Constraint:** `(aggregate_id, version)` unique. **No updates or deletes ever.**

### 3.2 `account_balances` (Cached Projection)

```sql
CREATE TABLE account_balances (
    account_id   TEXT PRIMARY KEY,
    name         TEXT NOT NULL,
    balance      DECIMAL(18,2) NOT NULL DEFAULT 0,
    last_version INT NOT NULL DEFAULT 0,
    created_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at   TIMESTAMPTZ NOT NULL DEFAULT now()
);
```

Avoids replaying all events on every page load. Updated by projection worker.

### 3.3 `users` (Auth — scaffolded)

```sql
CREATE TABLE users (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    username        VARCHAR(255) UNIQUE NOT NULL,
    email           VARCHAR(255) UNIQUE NOT NULL,
    hashed_password VARCHAR(255) NOT NULL
);
```

---

## 4. Event Types

| Type | data fields | Effect on balance |
|------|-------------|-------------------|
| `account_opened` | `name`, `initial_balance` | +initial_balance |
| `deposited` | `amount`, `note` | +amount |
| `withdrew` | `amount`, `note` | -amount |
| `transferred` | `amount`, `note`, `to_account` | -amount (source), +amount (target) |

Corrections are new events (same types) — never edits. A correction `withdrew` with
negative amount reverses the original.

---

## 5. Event Store Logic

### 5.1 `append_event(aggregate_id, event_type, data)`

1. Compute next version: `SELECT COALESCE(MAX(version), 0) + 1 FROM events WHERE aggregate_id = ?`
2. `INSERT INTO events (id, aggregate_id, event_type, data, version) VALUES (...)`
3. If `aggregate_id` ends in conflict (unique constraint on version) → retry (optimistic locking)
4. Return the new event with version

### 5.2 `get_events(aggregate_id, since_version=None)`

- `SELECT * FROM events WHERE aggregate_id = ? ORDER BY version ASC`
- Optionally filter by `version > since_version` for catch-up projections

### 5.3 `get_all_events(filters)`

- Filter by: `event_type`, `date_from`, `date_to`, `aggregate_id`
- Sort by: `created_at DESC`
- Paginate with cursor or offset

### 5.4 Replay to Compute Balance

```
balance = 0
for each event in get_events(aggregate_id), ordered by version:
    if event_type == 'account_opened': balance += data.initial_balance
    if event_type == 'deposited':       balance += data.amount
    if event_type == 'withdrew':        balance -= data.amount
    if event_type == 'transferred':     balance -= data.amount
return balance
```

### 5.5 Point-in-Time Balance

```
GET /accounts/{id}/balance?as_of=2026-07-01
Replay only events WHERE created_at <= as_of
```

---

## 6. API Endpoints

### 6.1 Auth (already scaffolded — no changes needed)

| Method | Path | Description | Auth |
|--------|------|-------------|------|
| POST | `/register` | Create account | No |
| POST | `/token` | Login | No |
| POST | `/token/refresh` | Rotate refresh token | Cookie |
| POST | `/logout` | Clear session | Cookie |
| GET | `/users/me/` | Current user | Cookie |

### 6.2 Accounts

| Method | Path | Description | Auth |
|--------|------|-------------|------|
| POST | `/accounts` | Open new account | Yes |
| GET | `/accounts` | List all with balances | Yes |
| GET | `/accounts/{id}` | Detail + events | Yes |
| GET | `/accounts/{id}/balance` | Point-in-time balance | Yes |

**POST /accounts** body:
```json
{ "name": "Chequing", "initial_balance": 0 }
```
Creates an `account_opened` event + initial balance row.

**GET /accounts** — returns from `account_balances` projection:
```json
[{ "id": "chq_1", "name": "Chequing", "balance": 1240.00 }]
```

### 6.3 Events / Transactions

| Method | Path | Description | Auth |
|--------|------|-------------|------|
| POST | `/accounts/{id}/events` | Append event | Yes |
| GET | `/events` | Global timeline | Yes |
| POST | `/transfer` | Cross-account transfer | Yes |

**POST /accounts/{id}/events** body:
```json
{ "type": "deposited", "data": { "amount": 2000, "note": "Paycheque" } }
```
1. Validates account exists
2. Calls `append_event()`
3. Updates `account_balances` projection
4. Returns new event + updated balance

**POST /transfer** body:
```json
{ "from_account": "chq_1", "to_account": "sav_1", "amount": 500, "note": "Savings transfer" }
```
1. Creates a `transferred` event on source
2. Creates a `deposited` event on target (linked via note)
3. Updates both projection rows
4. Returns both events

**GET /events** query params:
- `event_type` — filter by type
- `date_from`, `date_to` — date range
- `search` — text search in note field
- `limit`, `offset` — pagination

---

## 7. Projection Worker

On every event append, update the `account_balances` projection synchronously (MVP)
or asynchronously (post-MVP via Redis pub/sub or background task).

### Projection Update Logic

```python
async def update_balance(aggregate_id: str):
    events = await get_events(aggregate_id)
    balance = replay(events)
    last_version = events[-1].version
    await db.execute(
        UPDATE account_balances
        SET balance = :balance, last_version = :last_version, updated_at = now()
        WHERE account_id = :aggregate_id
    )
```

### Idempotent Ingestion

Every event should carry an optional **idempotency key** header (`Idempotency-Key`).
If the same key is seen twice, return the existing event instead of creating a duplicate.

---

## 8. Error Handling

| Scenario | HTTP Status | Detail |
|----------|-------------|--------|
| Account not found | 404 | No account with that ID |
| Insufficient funds | 422 | Withdrawal exceeds balance (optional check) |
| Duplicate version | 409 | Optimistic lock conflict — retry |
| Invalid event type | 422 | Not in allowed types |
| Auth failure | 401 | Missing or invalid token |
| Username taken | 409 | Duplicate username on register |
| Email taken | 409 | Duplicate email on register |
| Backend unreachable | 503 | Redis or Postgres connection error |

---

## 9. Validation Rules

- `amount` must be positive for `deposited`, `withdrew`, `transferred`
- `to_account` required for `transferred` and must be a different account
- Account names: 1-100 chars, alphanumeric + spaces
- Notes: optional, max 500 chars
- `version` is auto-computed — never accepted from client
- `id` is auto-generated — never accepted from client

---

## 10. Testing Requirements

| Layer | Tools | Coverage |
|-------|-------|----------|
| Unit (event store) | pytest | Append, replay, versioning, error cases |
| Unit (projections) | pytest | Balance calculation, catch-up, rebuild |
| Integration (API) | httpx + TestClient | All endpoints, auth flow, transfer |
| Integration (DB) | test PostgreSQL | Real DB queries, concurrent appends |
| E2E (optional) | Frontend + backend | Full register → create account → deposit flow |

### Key Test Cases

1. Append 3 events, replay, assert balance = sum
2. Transfer between accounts, assert both balances updated
3. Concurrent append to same account, assert no lost events
4. Rebuild projection from scratch, assert matches replay
5. Point-in-time balance matches events before that date
6. Invalid event type returns 422
7. Unauthenticated request returns 401
8. Duplicate username returns 409
9. Create account, deposit, withdraw, verify running total

---

## 11. File Structure

```
api/
├── app/
│   ├── main.py              # FastAPI app, CORS, exception handlers, route includes
│   ├── models.py            # SQLAlchemy ORM models
│   ├── schemas.py           # Pydantic request/response models
│   ├── core/
│   │   ├── auth.py          # JWT auth routes + dependency
│   │   ├── database.py      # Engine, session, init_db
│   │   ├── exceptions.py    # Custom exception classes
│   │   └── logging_config.py
│   ├── services/
│   │   ├── auth_service.py  # Token creation, password hashing
│   │   ├── user_service.py  # CRUD for users
│   │   ├── event_store.py   # append_event, get_events, replay  ← NEW
│   │   └── projections.py   # balance projection logic          ← NEW
│   ├── routers/
│   │   ├── accounts.py      # Account CRUD endpoints            ← NEW
│   │   └── events.py        # Event / transfer endpoints        ← NEW
│   ├── middleware/
│   │   └── logging_middleware.py
│   └── routes/
│       └── __init__.py      # (move routers here or keep separate)
├── alembic/
├── tests/
│   ├── unit/
│   │   ├── test_event_store.py
│   │   └── test_projections.py
│   └── integration/
│       ├── test_accounts.py
│       ├── test_events.py
│       └── test_transfer.py
└── process-compose.yaml
```

---

## 12. Implementation Order

### Phase 1 — Event Store (Foundation)
1. [ ] Define `events` table model in `models.py`
2. [ ] Implement `event_store.py`: `append_event()`, `get_events()`, `replay()`
3. [ ] Write Alembic migration for events table
4. [ ] Write unit tests for event store

### Phase 2 — Account Projection
5. [ ] Define `account_balances` table model
6. [ ] Implement `projections.py`: `update_balance()`, `rebuild_projection()`
7. [ ] Write migration for account_balances table
8. [ ] Write unit tests for projections

### Phase 3 — Account Routes
9. [ ] Implement `routers/accounts.py`: POST + GET + GET detail
10. [ ] Wire up event store + projection on account creation
11. [ ] Point-in-time balance endpoint
12. [ ] Integration tests for accounts

### Phase 4 — Event Routes
13. [ ] Implement `routers/events.py`: POST event, GET timeline
14. [ ] Implement `/transfer` endpoint
15. [ ] Validation: event types, amounts, account existence
16. [ ] Integration tests for events + transfer

### Phase 5 — Polish
17. [ ] Idempotency key support
18. [ ] Search/filter on event timeline
19. [ ] Pagination on GET /events
20. [ ] Snapshot & rebuild admin endpoints
21. [ ] Cryptographic event chain (hash linking)
22. [ ] Documentation pass

---

## 13. Future Considerations (Post-MVP)

- **Offline projection worker** — decouple balance updates via Redis pub/sub
- **Snapshots** — period balance snapshots so full replay isn't always needed
- **Cryptographic chain** — hash of previous event in each new event (tamper-proof)
- **Multi-user** — scope accounts/events to user_id
- **WebSocket push** — live balance updates to frontend
- **Export** — CSV/PDF statement generation from event replay
