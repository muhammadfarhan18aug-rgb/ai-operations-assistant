# AI Operations Assistant

Operations assistant for internal teams: foundation for a FastAPI backend, React frontend, and PostgreSQL datastore.

## Implementation Status

**Project foundation only.**

This repository currently includes the monorepo layout, a runnable FastAPI health endpoint, SQLAlchemy/Alembic wiring, Docker Compose for PostgreSQL, and a minimal React + Vite + TypeScript frontend shell. Authentication, domain models, agent/RAG features, tools, chat UI, and admin panels are not implemented yet.

## Technology Stack

| Layer | Stack |
| --- | --- |
| Backend | Python 3.11+, FastAPI, Pydantic, SQLAlchemy, Alembic |
| Frontend | React, TypeScript, Vite |
| Database | PostgreSQL 16 (Docker Compose) |

## Environment Setup

1. Copy the example env file (do not commit real secrets):

```bash
cp .env.example .env
```

2. Adjust values in `.env` as needed. Important placeholders:

- `DATABASE_URL`
- `JWT_SECRET` / `JWT_EXPIRE_MINUTES`
- `MODEL_PROVIDER` / `MODEL_NAME` / `MODEL_API_KEY`
- `EMBEDDING_PROVIDER` / `EMBEDDING_MODEL` / `EMBEDDING_API_KEY`
- `CORS_ORIGINS`

## Database Setup

Start PostgreSQL with Docker Compose from the repo root:

```bash
docker compose up -d
```

Confirm the container is healthy:

```bash
docker compose ps
```

## Backend Setup

```bash
cd backend
python -m venv .venv

# Windows
.venv\Scripts\activate

# macOS / Linux
source .venv/bin/activate

pip install -r requirements.txt
```

Ensure a `.env` exists at the repo root (copied from `.env.example`).

### Run backend

From `backend/` with the virtualenv active:

```bash
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

### Health endpoint

```bash
curl http://localhost:8000/health
```

Expected response:

```json
{"status":"ok","service":"AI Operations Assistant"}
```

### Alembic

From `backend/` with the virtualenv active and PostgreSQL running:

```bash
alembic current
```

This verifies Alembic can connect. No application migrations are required for this foundation step.

## Frontend Setup

```bash
cd frontend
npm install
```

### Run frontend

```bash
npm run dev
```

Open the URL Vite prints (typically `http://localhost:5173`). The page should show **AI Operations Assistant**.

## Project Layout

```text
ai-operations-assistant/
  backend/          # FastAPI application
  frontend/         # React + Vite + TypeScript
  docker-compose.yml
  .env.example
  README.md
```
