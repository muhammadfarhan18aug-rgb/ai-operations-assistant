# AI Operations Assistant

This project implements a local-first operations assistant with secure cookie-based authentication, PostgreSQL-backed capability checks, approval-gated writes, and grounded policy retrieval.

## D1. Routing and mixed requests

The agent has two explicit modes. With `MODEL_PROVIDER=openai` (or `openai-compatible`), a configured model performs structured request classification/action planning, and grounded policy answers are streamed from the provider. Without `MODEL_API_KEY`, the agent uses deterministic intent and argument extraction. The fallback is not an LLM-driven agent and has narrower language coverage.

Mixed workflows are represented as ordered graph steps. The reference request runs inventory lookup, computes a shortfall, pauses for purchase-order approval, then uses the generated order reference to draft a separately approved email. Each tool independently checks the acting user's database capability. Retrieved policy text is never passed to the action planner as authority.

Model or deterministic planning can misread novel phrasing, negation, or ambiguous quantities. Routing quality should be detected with a labeled intent/tool-selection set, event-level route logs, and regression tests for paraphrases and mixed-action requests. A failed provider call returns a readable failure and stops before any tool; it never falls back mid-request or fabricates success.

## D2. Write idempotency

The server creates a UUID request ID for each new chat submission. A resumed approval reuses the request-scoped key stored with its approval: `po-<request-id>` for the order and `email-<request-id>` for the email. Direct `POST /purchase-orders` requests require an `idempotency_key`; the server hashes it into an approval/tool key and scopes reuse to the submitting user and the same arguments. Repeating a resume cannot create another business record because approval status blocks a second resume and each tool also checks a unique database idempotency key.

The key is stored in `approval_requests.idempotency_key`, `orders.idempotency_key`, and `email_messages.idempotency_key`. It remains effective for as long as those rows are retained; there is no time-based key expiry or cleanup job. A genuinely new user submission receives a new request ID and is a distinct requested operation.

## D3. Pending approvals and inventory changes

Inventory is read before the graph creates a purchase-order draft. If inventory changes while approval is pending, the current implementation executes the approved quantity as drafted; it does not reserve stock, lock the product row, or automatically recalculate the shortfall. The approved order is still idempotent and revalidated for SKU, quantity, supplier, and authorization.

For production, approval should expire or require reconfirmation when its inventory snapshot is stale. At approval time the service should re-read inventory, recalculate the shortfall, and either update the draft for a new approval or explain why no order is now needed. Any reservation or procurement policy should be enforced transactionally by the database.

## D4. Quality evaluation

Evaluation should use a versioned set of single-step, mixed-step, denied, ambiguous, and adversarial examples. Track routing accuracy and per-intent precision/recall; tool-selection accuracy; argument exact match and field-level validity; authorization denial rate and unauthorized-write count; policy-answer coverage/refusal accuracy; citation precision and citation-to-claim correctness; and hallucination/no-context behavior. Report results by user capability and scenario type, and make unauthorized writes a zero-tolerance metric.

Evaluate both modes separately. The deterministic fallback is covered by exact workflow assertions and database outcomes. For model mode, add the same labeled cases plus structured-plan validity, provider failure rate, grounded response quality, and observed delta latency. Policy answers should be checked against seeded document rules and citation metadata in either mode.

## D5. Further improvement

The highest-value next improvement is a production-grade stale-inventory approval policy: reserve inventory or revalidate and recalculate the shortfall when approval resumes, then require a fresh human decision if the action arguments materially change. This closes the gap between a correct approval snapshot and changing operational data without weakening the human gate.

## Demo seed and identities

The idempotent seed creates or reconciles these exact users and capabilities:

| Email | Admin | Capabilities |
| --- | --- | --- |
| `admin@assistant.test` | Yes | `policy:read`, `inventory:read`, `order:create`, `email:send` |
| `ali@assistant.test` | No | `policy:read`, `inventory:read` |
| `sara@assistant.test` | No | `policy:read`, `inventory:read`, `order:create` |
| `dave@assistant.test` | No | none |

Set `SEED_PASSWORD` or all four per-user seed password environment variables in `.env`. The single demo command creates the users and capabilities, upserts 16 inventory products (including `SKU-1043` at exactly 120 units), and indexes the repository's leave, expense reimbursement, inventory, and procurement policies with chunks and metadata:

```powershell
Set-Location backend
python -m app.seed.seed
```

## Local setup

Prerequisites are Python 3.11+, PostgreSQL, and Node.js/npm. Configure `.env`, create the `ai_operations` database if needed, and apply migrations:

```powershell
Set-Location backend
..\.venv\Scripts\alembic.exe upgrade head
..\.venv\Scripts\alembic.exe current
python -m app.seed.seed
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

In another terminal:

```powershell
Set-Location frontend
npm install
npm run dev
```

The application uses a durable PostgreSQL LangGraph checkpointer. The compiled graph and checkpointer are created in the FastAPI lifespan; startup fails if PostgreSQL checkpointing cannot be initialized. Resume identity and thread ownership are resolved server-side from the authenticated user and approval record.

## Model configuration

Real model mode uses the OpenAI Chat Completions API. Configure these values in `.env`; provide your own key locally and never commit it:

```env
MODEL_PROVIDER=openai
MODEL_NAME=gpt-4o-mini
MODEL_API_KEY=
MODEL_BASE_URL=
```

`openai-compatible` is also supported when `MODEL_BASE_URL` points to an OpenAI-compatible endpoint. If no API key is configured, the deterministic fallback is selected. If a configured provider fails, the request fails closed with a readable message and no write is executed. Model output only proposes routing and arguments: DB-backed capabilities, schema validation, LangGraph approval interrupts, idempotency, thread ownership, and audit logging remain independent enforcement boundaries.

In model mode, grounded answer tokens are forwarded as SSE `assistant_delta` events as the provider yields them. Routing and tool events remain available in both modes; deterministic mode does not emit artificial token chunks.

## Security and admin operations

JWTs are issued in an HttpOnly cookie. The frontend sends requests with `credentials: 'include'` and does not persist tokens in browser storage. Database capabilities are authoritative, and every write tool rechecks permission after the graph interrupt. Admin APIs enforce admin authorization independently of the UI.

Admin routes are `/admin/users`, `/admin/documents`, and `/admin/activity`. Document upload indexes chunks immediately and removal withdraws a document from retrieval. Direct order requests use `POST /purchase-orders` with SKU, quantity, supplier, and (for authorized submissions) a stable `idempotency_key`; authorized callers receive HTTP 202 and a pending approval, never an immediate order. The capability check runs before the authorized-request idempotency requirement, so Ali receives 403 on a direct valid order request even if that field is omitted. The mock email tool stores one email record, prints it to the server console, and writes an audit event; it does not send SMTP mail.

## Reference scenario

The exact one-message prompt is: “Do we have 200 units of SKU-1043? If not, raise a purchase order with the supplier for the shortfall, and email me a confirmation once it's done.” Inventory is read first, the order and email use distinct approval rows, and the email body contains the generated order reference.

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
- server-side cancellation of an in-flight graph run
- production-grade secret management

Cancellation is not implemented; closing the browser stream does not claim to stop server-side graph work. Real SMTP and production-grade secret management remain out of scope.
