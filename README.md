# AI Operations Assistant

This project implements a local-first operations assistant with secure cookie-based authentication, PostgreSQL-backed capability checks, approval-gated writes, and grounded policy retrieval.

## D1. Functional scope

- Authenticated operator chat with deterministic routing.
- Policy-grounded document retrieval with citations.
- Inventory lookups gated by `inventory:read`.
- Purchase orders gated by `order:create` and human approval before write execution.
- Email dispatch as a mock local backend action gated by `email:send` and human approval.
- Administrator access for user, document, and audit review.

## D2. Seeded users and password configuration

The supported demo user identities are:

| Email | Admin | Capabilities |
| --- | --- | --- |
| `admin@assistant.test` | Yes | `policy:read`, `inventory:read`, `order:create`, `email:send` |
| `ali@assistant.test` | No | `policy:read`, `inventory:read` |
| `sara@assistant.test` | No | `policy:read`, `inventory:read`, `order:create` |
| `dave@assistant.test` | No | none |

Set the demo seed password in `.env` using either a shared value or the per-user variables:

```env
SEED_PASSWORD=change_me_for_local_demo
# optional compatibility values:
# SEED_ADMIN_PASSWORD=change_me_for_local_demo
# SEED_ALI_PASSWORD=change_me_for_local_demo
# SEED_SARA_PASSWORD=change_me_for_local_demo
# SEED_DAVE_PASSWORD=change_me_for_local_demo
```

The seed command is:

```powershell
Set-Location backend
python -m app.seed.seed
```

The seed is idempotent; it creates missing users/capability rows without duplicating any existing grant or user record.

## D3. Database, migrations, and local setup

Prerequisites:
- Python 3.11+
- PostgreSQL running locally on `localhost:5432`
- Node.js/npm for the frontend

Create the database and configure `.env` before running migrations:

```powershell
createdb ai_operations
Copy-Item .env.example .env
```

Apply schema changes:

```powershell
Set-Location backend
..\.venv\Scripts\alembic.exe upgrade head
..\.venv\Scripts\alembic.exe current
```

Run the backend:

```powershell
Set-Location backend
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

Run the frontend:

```powershell
Set-Location frontend
npm install
npm run dev
```

## D4. Security and approval model

- JWT identity is issued as a signed token and stored in an HttpOnly cookie.
- Protected routes read the authenticated user from the secure cookie, not browser storage.
- The database is the source of truth for user capabilities.
- Tool execution revalidates capability at the tool boundary.
- Purchase orders and emails progress through a pending approval state before any write executes.
- Approval edits are revalidated before execution.
- Idempotency keys prevent duplicate write execution.
- Policy documents are retrieved as reference content only and are never treated as an authorization decision.
- Prompt injection defense relies on retrieval citations and explicit tool authorization rather than trusting model intent.

## D5. Admin, policy retrieval, and frontend behavior

The admin routes are:
- `/admin/users`
- `/admin/documents`
- `/admin/activity`

These routes enforce admin-only access. The backend remains authoritative; the frontend never fabricates access decisions.

The frontend uses `fetch(..., { credentials: 'include' })` and does not persist JWTs in `localStorage` or `sessionStorage`. Browser auth is cookie-based.

Policy retrieval uses a local document store and returns citations. Uploaded documents can be indexed and later removed; after removal the same question should no longer be answered from that document.

The mock email flow writes a local email record, prints the warning/dispatch to the server console, and creates an audit log for admin review. It does not send real SMTP mail.

## Reference scenario

The project includes a reference scenario in which an authorized user checks inventory, then requests a purchase order for a shortfall, and approves the order through the approval workflow. The same flow is used for email dispatch after capability recheck and separate approval.

## Testing

Backend validation:

```powershell
Set-Location C:\Users\muham_tvqf2k3\Projects\ai-operations-assistant\backend
..\.venv\Scripts\pytest.exe -q
```

Frontend validation:

```powershell
Set-Location C:\Users\muham_tvqf2k3\Projects\ai-operations-assistant\frontend
npm test -- --run
npm run build
```

## Deferred functionality

This repository intentionally does not include or claim:
- external SMTP providers
- Docker orchestration
- real hosted vector infrastructure
- live LLM model calls
- production-grade secret management

The assessment requirement flow is implemented and documented here; real external integrations remain intentionally out of scope.
