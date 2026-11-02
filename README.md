# Supply Chain Demand Forecasting & Inventory Optimization AI

Full-stack supply-chain analytics application. The current release includes a FastAPI service, React/Vite dashboard, CSV ingestion, chronological ML forecasting, inventory reorder calculations, supplier APIs and optional OpenAI assistance.

## Deployment targets
- Render single-service dashboard/API: `https://supply-chain-demand-api.onrender.com/`
- GitHub Pages frontend (automated workflow): `https://99240040703-beep.github.io/supply-chain-demand-forecasting-ai/`
- API health: `/health`; interactive API docs: `/docs`

## Stack
- Frontend: React, TypeScript, Vite, Recharts, Lucide
- Backend: FastAPI, SQLAlchemy, Pandas, scikit-learn
- Database: PostgreSQL in production; SQLite for local development
- Hosting: Vercel frontend, Render API

## Run locally
Backend:
```bash
cd backend
python -m venv .venv
# Windows: .venv\Scripts\activate
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
uvicorn app.main:app --reload
```
Frontend:
```bash
cd frontend
npm install
npm run dev
```
API docs: http://localhost:8000/docs

## Dataset
Upload CSV/XLSX with required columns `Date`, `Product_ID`, `Quantity_Sold`. Optional: Product_Name, Category, Unit_Price, Inventory_Level, Promotion, Supplier_ID, Lead_Time, Warehouse_ID. Download a sample at `GET /api/datasets/sample`.

## Forecasting
Daily product demand is aggregated before time-series feature creation. Validation is chronological (never random shuffled). Linear Regression and Random Forest are compared using MAE, RMSE and WAPE. Recursive predictions use only past observations. Products with insufficient history are not forecast.

## Inventory
ROP = average daily demand × lead time + safety stock. Safety stock uses observed daily demand variation. The recommended order quantity targets 30 days of demand. This is an explainable baseline and should be tuned for supplier lead-time variation, service level, MOQ and open POs before operational use.

## Purchase orders and alerts
The dashboard supports supplier management, inventory alerts, draft purchase orders, submission, approval, receipt and cancellation. Receiving an approved order adds its quantity to the product stock. Forecast validation metrics (MAE, RMSE, WAPE) are saved per user and exposed in the Forecasting screen.

## Environment
See `backend/.env.example`. Set `DATABASE_URL`, `SECRET_KEY`, `CORS_ORIGINS`, optional `OPENAI_API_KEY` on Render, and `VITE_API_URL` on Vercel. Never commit secrets.

## Limitations
This is an initial working foundation, not a certified enterprise system. Alembic migrations, durable background jobs, purchase-order approval lifecycle, supplier delivery events, advanced notifications, refresh-token revocation, rate limiting, Excel/PDF exports and expanded integration tests remain future work. Free Render databases are time-limited; configure a durable database before production business use.
