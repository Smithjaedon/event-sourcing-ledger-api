# api

## Prerequisites

- Python 3.12+
- [uv](https://docs.astral.sh/uv/) — package manager
- [process-compose](https://f1bonacc1.github.io/process-compose/) — process runner
- Redis — session/rate-limit storage

```bash
# Install uv (if not installed)
curl -LsSf https://astral.sh/uv/install.sh | sh

# Install process-compose
brew install process-compose  # macOS
# or: go install github.com/F1bonacc1/process-compose@latest

# Install Redis
brew install redis  # macOS; or use the docker-compose below
```

## Quick start

```bash
# Scaffold the project (from scratch)
spark create

# Or from inside the project directory, start all services
spark dev
```

`spark dev` starts uvicorn (hot-reload) + redis via process-compose.

## Common commands

### Dependencies

```bash
uv sync                  # Install all dependencies from lockfile
uv add <package>         # Add a dependency
uv remove <package>      # Remove a dependency
uv lock                  # Regenerate lockfile (no sync)
```

### Server

```bash
uv run uvicorn app.main:app --reload            # Dev server (manual)
uv run uvicorn app.main:app --port 8000          # Production-style
spark dev                                        # Full stack (app + redis)
```

Use `--host 0.0.0.0` to listen on all interfaces.

### Database migrations (Alembic)

```bash
# Create a new migration (detect model changes)
uv run alembic revision --autogenerate -m "description"

# Apply pending migrations
uv run alembic upgrade head

# Rollback one step
uv run alembic downgrade -1

# Rollback to a specific revision
uv run alembic downgrade <revision_id>

# View migration history
uv run alembic history

# View current revision
uv run alembic current

# Show pending migrations
uv run alembic check
```

**Workflow:**

1. Edit models in `app/models.py`
2. Run `uv run alembic revision --autogenerate -m "add field"` — generates a migration in `alembic/versions/`
3. Review the generated migration file
4. Run `uv run alembic upgrade head` — applies changes

> **Note:** Migrations run against the database configured in `.env`. Set `DB_USER`, `DB_PASSWORD`, `DB_HOST`, `DB_PORT`, `DB_NAME` before running.

### Code quality

```bash
uv run ruff check .       # Lint
uv run ruff format .      # Format
uv run ruff check --fix . # Auto-fix
```

## Environment variables

| Variable | Default | Description |
|---|---|---|
| `SECRET_KEY` | *(auto-generated)* | JWT signing key |
| `DB_USER` | — | Database user |
| `DB_PASSWORD` | — | Database password |
| `DB_HOST` | `localhost` | Database host |
| `DB_PORT` | — | Database port |
| `DB_NAME` | — | Database name |
| `REDIS_URL` | `redis://localhost:6379` | Redis connection string |
| `PORT` | `8000` | Application port |

Copy `.env.example` to `.env` and fill in the values:

```bash
cp .env.example .env
```

## Project structure

```
.
├── app/
│   ├── core/           # Database, auth, exceptions, logging
│   ├── middleware/      # Request logging middleware
│   ├── models.py       # SQLAlchemy models
│   ├── schemas.py      # Pydantic request/response schemas
│   ├── services/       # Business logic (auth, user)
│   └── main.py         # FastAPI app entry point
├── alembic/            # Migration environment + versions
├── tests/
│   ├── unit/
│   └── integrations/
├── .env.example
├── process-compose.yaml
└── pyproject.toml
```