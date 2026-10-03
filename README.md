# AI Operations Assistant

AI Operations Assistant is a foundation project for a backend-powered operations assistant platform. This step establishes the clean monorepo structure, configuration, environment setup, health endpoint, database wiring, and frontend shell without implementing authentication, AI workflows, or operational product features yet.

## Technology stack

- Backend: Python 3.11+, FastAPI, Pydantic Settings, SQLAlchemy 2.x, Alembic, asyncpg
- Frontend: React, TypeScript, Vite
- Database: PostgreSQL (local installation, not Dockerized)

## Project structure

```text
ai-operations-assistant/
├── backend/
│   ├── alembic/
│   ├── app/
│   ├── tests/
│   ├── alembic.ini
│   ├── pytest.ini
│   ├── requirements.txt
│   └── .venv/  (local virtual environment; git-ignored)
├── frontend/
├── .env.example
├── .gitignore
├── README.md
└── .venv/      (project-level virtual environment; git-ignored)
```

## Prerequisites

- Python 3.11+
- Node.js 18+
- PostgreSQL installed locally on the developer machine
- Git

## Local PostgreSQL requirement

This project does not use Docker. PostgreSQL is expected to be installed and running locally on the machine. The application connects through the `DATABASE_URL` environment variable, which should target a local PostgreSQL instance.

### Create the PostgreSQL database

After PostgreSQL is installed and started locally, create a database such as:

```bash
createdb ai_operations
```

Or with psql:

```bash
psql -U postgres -d postgres -c "CREATE DATABASE ai_operations;"
```

## Python virtual environment

From the project root:

```bash
python -m venv .venv
```

Activate it:

- Windows PowerShell:

```powershell
.\.venv\Scripts\Activate.ps1
```

- Windows Command Prompt:

```cmd
.venv\Scripts\activate.bat
```

- macOS / Linux:

```bash
source .venv/bin/activate
```

## Backend installation

```bash
cd backend
pip install -r requirements.txt
```

## Configure environment variables

Copy the example environment file:

```bash
copy .env.example .env
```

On macOS / Linux:

```bash
cp .env.example .env
```

Then update the values in `.env` for your local PostgreSQL and local development settings.

Required variables include:

- `DATABASE_URL`
- `JWT_SECRET`
- `JWT_EXPIRE_MINUTES`
- `MODEL_PROVIDER`
- `MODEL_NAME`
- `MODEL_API_KEY`
- `EMBEDDING_PROVIDER`
- `EMBEDDING_MODEL`
- `EMBEDDING_API_KEY`
- `CORS_ORIGINS`

## Alembic

From the `backend` directory with the virtual environment active:

```bash
alembic current
```

Additional verification:

```bash
alembic check
```

This foundation intentionally has no business-model migrations yet, so the expected result is a successful connection check without fake migration history.

## Start FastAPI

From the project root with the virtual environment active:

```bash
cd backend
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

## Frontend installation

```bash
cd frontend
npm install
```

## Start React frontend

```bash
npm run dev
```

The Vite dev server will print a local URL such as `http://localhost:5173`.

## Health endpoint

The backend exposes:

```http
GET /health
```

Example response:

```json
{"status": "ok"}
```

## Current implementation status

Current status: project foundation only.

This project does not yet implement authentication, AI agents, RAG, tools, approvals, admin features, or the chat system. The current step is limited to a clean project foundation that is ready for future extension.
