# AI Operations Assistant

AI Operations Assistant is a backend-first operations assistant platform. This repository now includes the Step 1 foundation, the Step 2 PostgreSQL schema, and the Step 3 authentication and capability-authorization foundation.

## Technology stack

- Backend: Python 3.11+, FastAPI, Pydantic Settings, SQLAlchemy 2.x, Alembic, asyncpg
- Authentication: PyJWT, Argon2id via `argon2-cffi`
- Frontend: React, TypeScript, Vite
- Database: PostgreSQL (local installation, not Dockerized)

## Authentication architecture

Authentication and authorization are implemented with a strict backend-only model:

- JWT establishes user identity.
- PostgreSQL is the source of truth for authorization.
- Capabilities are loaded from the `user_capabilities` table at request time.
- The LLM, frontend, or request payload is never trusted for permission checks.
- Admin authorization is based on the database field `users.is_admin`.

## Password hashing

Passwords are hashed with Argon2id. The app never stores or returns plaintext passwords. Password hashes are stored in the existing `users.password_hash` field. The `hash_password` and `verify_password` helpers are in the password service and are used by the authentication flow.

## JWT flow

- The client sends `POST /auth/login` with `email` and `password`.
- The server validates the credentials against PostgreSQL.
- On success, the server issues a JWT containing the user ID in the `sub` claim.
- The backend decodes and validates that JWT in the authenticated-user dependency.
- Capabilities are reloaded from the database so a token can remain valid while permissions change.

## Seeded demo users

The app includes four seeded demo users:

- admin@cellutech.com
- ops@cellutech.com
- manager@cellutech.com
- viewer@cellutech.com

These are created by the demo seed command and are idempotent. The exact demo passwords are configured through environment variables and must be set before seeding.

## Seed command

From the project root or backend directory, with the virtual environment activated:

```bash
cd backend
python -m app.seed.seed
```

This command:

- connects to PostgreSQL
- creates the four required users if missing
- hashes passwords with Argon2id
- creates missing capabilities without duplicates
- prints a safe summary without emitting passwords

## Demo credentials

The seed command expects these environment variables to be supplied in `.env`:

- `SEED_ADMIN_PASSWORD`
- `SEED_OPS_PASSWORD`
- `SEED_MANAGER_PASSWORD`
- `SEED_VIEWER_PASSWORD`

These are development/demo credentials only and must not be used in production. They are placeholders in `.env.example` and should be replaced before non-local use.

## Default capability mapping

- admin@cellutech.com: `is_admin = true`, capabilities `policy:read`, `inventory:read`, `order:create`, `email:send`
- ops@cellutech.com: `policy:read`, `inventory:read`, `order:create`, `email:send`
- manager@cellutech.com: `policy:read`, `inventory:read`, `order:create`
- viewer@cellutech.com: `policy:read`, `inventory:read`

## Obtaining a token

```bash
curl -X POST http://localhost:8000/auth/login \
  -H "Content-Type: application/json" \
  -d '{"email":"admin@cellutech.com","password":"your-seed-password"}'
```

Example response:

```json
{"access_token":"...","token_type":"bearer"}
```

## Calling /auth/me

```bash
curl http://localhost:8000/auth/me \
  -H "Authorization: Bearer <token>"
```

The response contains safe identity data and the authenticated user's capabilities, but never includes `password_hash`.

## Authorization verification endpoints

The project includes temporary internal development endpoints that prove backend-only authorization enforcement without attaching to real operational functionality:

- `GET /authz/inventory-test` requires `inventory:read`
- `GET /authz/order-test` requires `order:create`
- `GET /authz/email-test` requires `email:send`

These are clearly marked as internal development verification endpoints and are not operational tool implementations.

## Local PostgreSQL requirement

This project expects PostgreSQL installed locally with a database named `ai_operations`.

### Create the database

```bash
createdb ai_operations
```

or:

```bash
psql -U postgres -d postgres -c "CREATE DATABASE ai_operations;"
```

## Environment variables

Required values in `.env` include:

- `DATABASE_URL`
- `JWT_SECRET`
- `JWT_EXPIRE_MINUTES`
- `SEED_ADMIN_PASSWORD`
- `SEED_OPS_PASSWORD`
- `SEED_MANAGER_PASSWORD`
- `SEED_VIEWER_PASSWORD`
- `CORS_ORIGINS`

The app must not run with a weak or hardcoded JWT secret outside local development.

## FastAPI startup

```bash
cd backend
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

## Testing

```bash
cd backend
pytest -q
```

## Implementation status

Step 3 complete: Authentication and capability-based authorization foundation implemented.

This project does not claim to implement LangGraph, RAG, operational tools, email sending, purchase order execution, human approval, streaming chat, or admin UI in this step.
