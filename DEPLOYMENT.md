# Deployment checklist

## Render API
1. Connect this repository to a Render Web Service.
2. Runtime Python; root directory `backend`.
3. Build: `pip install -r requirements.txt`
4. Start: `uvicorn app.main:app --host 0.0.0.0 --port $PORT`
5. Health check: `/health`
6. Configure `DATABASE_URL` to a durable PostgreSQL database, `SECRET_KEY` to a strong random secret, `CORS_ORIGINS` to the exact Vercel frontend origin, and optionally `OPENAI_API_KEY`.

## Vercel frontend
1. Import this GitHub repository.
2. Set root directory to `frontend`.
3. Framework: Vite; build: `npm run build`; output: `dist`.
4. Set `VITE_API_URL` to the deployed Render API origin.

## Database
Use a dedicated PostgreSQL instance for this application. Do not reuse another application's database. Free database plans may expire and are not appropriate for durable business data.

## Verify
- GET `/health` returns status ok and database connected.
- Register and log in.
- Download and upload the sample dataset.
- Train a forecast and inspect model metrics.
- Check inventory recommendations and CSV export.
