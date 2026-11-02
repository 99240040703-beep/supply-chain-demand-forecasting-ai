# Supply Chain Demand Forecasting & Inventory Optimization AI

Full-stack supply-chain analytics application with a browser dashboard, FastAPI API, CSV/XLSX ingestion, chronological ML forecasting, inventory optimization, supplier management, purchase-order workflow, alerts and optional OpenAI assistance.

## Live deployment

- **Dashboard and API:** https://supply-chain-demand-api.onrender.com/
- **API health:** https://supply-chain-demand-api.onrender.com/health
- **Interactive API docs:** https://supply-chain-demand-api.onrender.com/docs
- **Source repository:** https://github.com/99240040703-beep/supply-chain-demand-forecasting-ai

The production dashboard is served by FastAPI from `backend/app/static/index.html`, so the browser UI and API share the same origin.

## Stack

- Frontend: responsive HTML/CSS/JavaScript dashboard; React/Vite source is also in `frontend/`
- Backend: FastAPI, SQLAlchemy, Pandas, scikit-learn
- Database: SQLite for local development; PostgreSQL supported for production
- AI assistant: OpenAI Chat Completions API using configurable `OPENAI_MODEL` (default `gpt-4o-mini`)
- Hosting: Render

## Run locally

```bash
cd backend
python -m venv .venv
# Windows: .venv\\Scripts\\activate
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
uvicorn app.main:app --reload
```

API docs: http://localhost:8000/docs

## Production database setup (Render)

1. Create a PostgreSQL database in the same Render workspace and region as the web service.
2. Copy its **Internal Database URL** from the database's Render dashboard.
3. Open the `supply-chain-demand-api` web service → Environment.
4. Set `DATABASE_URL` to that internal URL. Keep the URL private; do not commit it or paste it into chat.
5. Save changes and allow Render to redeploy. The API's `/health` endpoint checks the database connection.
6. Verify that `/health` returns `database: connected` and `database_type: postgresql`.

The app creates missing SQLAlchemy tables at startup. For long-term production schema evolution, add Alembic migrations before changing existing table definitions. Existing SQLite records are not automatically copied into PostgreSQL; export/import them before switching if you need to preserve existing users and datasets.

**Important:** Render's Free PostgreSQL databases are temporary and expire after the provider's stated trial period. Use a paid database or another durable PostgreSQL provider for data that must be retained. Do not point this project at a database belonging to another application.

## OpenAI assistant setup

1. Create an API key in your OpenAI developer account and ensure billing/credits are active.
2. In Render → `supply-chain-demand-api` → Environment, add `OPENAI_API_KEY` with the key value.
3. Optionally set `OPENAI_MODEL` to a model available to your API project (default: `gpt-4o-mini`).
4. Save changes and wait for redeployment.
5. Open **AI Assistant** in the dashboard and ask a question. `GET /api/ai/status` reports whether the key is configured; it never returns the key.

Never commit secrets or paste API keys into source files or chat. ChatGPT subscriptions and API billing are separate.

## Dataset

Upload CSV/XLSX with required columns `Date`, `Product_ID`, `Quantity_Sold`. Optional: Product_Name, Category, Unit_Price, Inventory_Level, Promotion, Supplier_ID, Lead_Time, Warehouse_ID. Download a sample at `GET /api/datasets/sample`.

## Forecasting and inventory

Daily product demand is aggregated before time-series feature creation. Validation is chronological (never random shuffled). Linear Regression and Random Forest are compared using MAE, RMSE and WAPE. Products with insufficient history are not forecast.

ROP = average daily demand × lead time + safety stock. The recommended order quantity targets 30 days of demand. Tune for supplier lead-time variation, service level, MOQ and open purchase orders before operational use.

## AI assistant

The authenticated `POST /api/ai/chat` endpoint grounds answers in the signed-in user's dashboard totals, inventory recommendations, suppliers and recent forecasts. It does not expose the API key to the browser. Configure `OPENAI_API_KEY` on the server; configure `OPENAI_MODEL` only if you want to override the default.

## Environment variables

- `SECRET_KEY`: strong random secret
- `DATABASE_URL`: PostgreSQL internal connection URL in production; SQLite default for local use
- `CORS_ORIGINS`: frontend origins when hosting separately
- `OPENAI_API_KEY`: secret OpenAI API key
- `OPENAI_MODEL`: optional model name, default `gpt-4o-mini`
- `OPENAI_TIMEOUT_SECONDS`: optional provider timeout, default 35

## Limitations

This is a project/demo foundation, not a certified enterprise system. SQLite on an ephemeral free web-service filesystem is not durable. The app does not automatically migrate data from SQLite to PostgreSQL. Database schema migrations, scheduled backups, rate limiting and monitoring should be added before real business use.
