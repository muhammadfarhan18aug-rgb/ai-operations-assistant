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

## Grounded policy Q&A (Step 6)

Step 6 adds a repository-backed policy grounding pipeline that answers knowledge questions from actual policy documents instead of relying on ungrounded model memory.

### Policy document ingestion

- Policy source documents live under `backend/app/policies/documents/`.
- The ingestion service loads Markdown policy files, derives stable document metadata, and writes the source text to the `documents` table.
- Each document is chunked into readable sections and stored as `document_chunks` rows with ordering metadata and embeddings references.

### Local embedding and retrieval

- The development embedding service uses a deterministic local hash-based vector representation.
- A lightweight local vector store ranks chunk similarity against the current user question.
- Retrieval includes citation metadata, policy section labels, document identifiers, and version/source details.
- The implementation enforces a minimum relevance threshold so unrelated questions return an explicit `no relevant policy found` result instead of a false match.

### Grounded responses and safety boundaries

- The knowledge branch reads the latest user message and calls the retrieval service before constructing a response.
- Responses are grounded in retrieved policy snippets and cite the matching document metadata.
- Prompt injection text inside policy documents is treated as content, not executable instruction.
- Policy retrieval does not grant capabilities, execute operational tools, or bypass the database-authoritative authorization model established in earlier steps.
- The operational tools remain separate from the knowledge branch and continue to require the existing DB-backed capability checks.

### Current limits

- This is a local deterministic retrieval approach suited to development and validation.
- It does not add external vector databases, external embedding APIs, or later approval workflows.
- It does not change the separate operational tool authorization layer or any Step 1–5 authorization behavior.

## Operational tools and security

This project includes a secure operational tool layer built on the existing PostgreSQL-backed capability model.

### Tool registry

The operational tools are explicitly allowlisted and are not selected dynamically from user input:

- `inventory_lookup` requires `inventory:read`
- `purchase_order_create` requires `order:create`
- `email_send` requires `email:send`
- `policy_lookup` requires `policy:read`

No dynamic import, `eval`, `exec`, shell execution, or arbitrary Python function dispatch is permitted.

### Tool context

Every tool receives a trusted `ToolContext` generated by the backend, containing the authenticated user ID, the thread ID, and a per-execution identifier. The browser may not submit trusted `user_id`, `capabilities`, `is_admin`, `approved`, or `role` values for authorization decisions.

### Authorization flow

Each protected tool follows the same flow:

1. accept a trusted `ToolContext`
2. validate business input
3. load the active user from PostgreSQL
4. verify the user is active
5. verify the required capability from `user_capabilities`
6. perform the business operation only after authorization passes
7. write an audit log entry for the action
8. return a structured result or a safe authorization error

### Idempotency and transactions

The purchase order and email tools use database-backed idempotency keys. A repeated request with the same key returns the original result instead of creating a duplicate record. Orders are created with a unique `idempotency_key` constraint enforced by PostgreSQL.

### Audit logging

Operational actions write audit events to the `audit_logs` table with the authenticated user, tool name, arguments, thread id, and outcome. Passwords, JWTs, and external secrets are never logged.

### Scope and deferred work

This step intentionally does not implement:

- RAG or policy vector search
- human approval workflow
- real LLM tool calling
- frontend functionality
- real external email delivery
- real purchase order execution outside the authorized backend boundary

## Implementation status

Step 5 operational tool layer and tool-level authorization are implemented and protected by database-backed capability checks.

Step 4 complete: LangGraph orchestration foundation with knowledge, action, and unknown branches, PostgreSQL checkpoint persistence, authenticated chat endpoint, and thread ownership enforcement.
