# MacroPulse

Research platform for how gold (XAU/USD) and USD FX majors react to US macroeconomic
announcements, built on point-in-time data with strict look-ahead-bias protection.
Research and prediction only — **no trading execution, not investment advice.**

See [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) for design, data-source findings, limitations
and the phase plan.

## Setup

```bash
cp .env.example .env          # then fill in FRED_API_KEY and DATABASE_URL
cd backend
uv sync                       # Python 3.12 venv + deps

# database (once DATABASE_URL points at PostgreSQL)
createdb -p 5433 macropulse   # or via psql
uv run alembic upgrade head

uv run uvicorn app.api.main:app --reload   # API docs: http://127.0.0.1:8000/docs
```

## Data pipeline (in order)

```bash
cd backend
uv run python -m app.ingestion.cli prices --source kaggle_octafx_xauusd   # gold 1m -> silver Parquet
uv run python -m app.ingestion.cli fred-events --priority                 # CPI/PCE/NFP/UNRATE events
uv run python -m app.ingestion.cli fomc                                   # FOMC decisions
uv run python -m app.ingestion.cli windows --instrument XAUUSD            # event price windows
```
Add `--database-url sqlite:///dev.db` before the subcommand to run without PostgreSQL.

## Tests

```bash
cd backend
uv run pytest                 # offline unit tests
uv run pytest -m live         # hits FRED with your key
uv run pytest -m postgres     # migration check against DATABASE_URL
```

## Layout

```
config/      events.yaml (releases & indicators), instruments.yaml
backend/     FastAPI app, providers, models, migrations, tests
data/        bronze / silver / gold data lake (git-ignored)
models/      trained model artifacts & registry exports
docs/        architecture and plans
```
