---
name: cloud-video-production-qa-debugger
description: Diagnose and exercise the Firefly Cloud Video Production public API in the dedicated QA environment at https://medi-qa.fireflyfusion.cn. Use when checking QA gateway health, QA authentication, local image/video upload, Cloud make/poll/queryResult behavior, idempotency, Webhook delivery, error codes, or a known QA conversation_id. Use only the isolated FIREFLY_MVA_QA_API_KEY credential; never use this skill for production, staging, or a customer production key.
---

# Cloud Video Production QA Debugger

Debug the Cloud template-production flow in QA while keeping requests, credentials, identifiers, and evidence isolated from production.

## Load references

- Read `references/qa-debug-playbook.md` before running any QA request.
- Read `references/api-contract.md` before constructing or interpreting upload, make, Poll, or queryResult requests.
- Read `references/webhook-contract.md` when diagnosing callbacks or verifying signatures.
- Use `references/openapi.yaml` for schema validation or generated clients.

## Pin the QA boundary

Use exactly this origin:

```text
https://medi-qa.fireflyfusion.cn
```

Use only the environment variable:

```text
FIREFLY_MVA_QA_API_KEY
```

Never read a generic API-key variable and never fall back to a production credential variable. Do not accept a production Base URL or production key for convenience. If the requested target is not the pinned QA origin, stop and use a different environment-specific workflow.

Require the QA key to have `produce` scope. Ask the operator to provision or rotate it through the QA credential control plane when it is missing, rejected, or suspected exposed. Never ask the user to paste its plaintext into chat.

## Protect credentials

- Load the key from the process environment or an approved local secret manager.
- Check only whether `FIREFLY_MVA_QA_API_KEY` is present; never print its value.
- Do not run `env`, `printenv`, `set`, `set -x`, `curl -v`, or commands that echo request headers.
- Never write a real key into this Skill, shell history, source files, `.env.example`, generated reports, screenshots, or logs.
- Redact authorization headers, signed URL query strings, Webhook signatures, and customer media content from evidence.

## Choose the least-mutating diagnostic

Classify the problem before calling an endpoint:

1. For reachability or gateway failures, call `GET /api/rest/mva/health` first.
2. For a known `conversation_id`, call `POST /api/rest/mva/out/cloud/queryResult` first because it reads persisted parent-task state without refreshing the renderer.
3. Use `POST /api/rest/mva/out/cloud/poll` only when downstream render reconciliation is required or the user explicitly asks for current progress.
4. Upload a local file only when the user explicitly selected it and the current runtime may read it. Upload stores an object even though it does not create a production task.
5. Call `POST /api/rest/mva/out/cloud/make` only when the user asks to create a QA task or an agreed smoke test requires one. It creates durable QA task state unless the request is an idempotent replay.

Do not probe production as a comparison step.

## Run the QA workflow

### Verify prerequisites

- Confirm the effective origin is exactly `https://medi-qa.fireflyfusion.cn`.
- Confirm `FIREFLY_MVA_QA_API_KEY` is non-empty without displaying it.
- Generate a unique `X-Request-ID` for each HTTP request.
- Generate and persist one QA-only `outer_request_id` before the first `/make` attempt.
- Prefix generated business identifiers with `qa-` so they cannot be confused with production identifiers.

### Upload selected local media

Send repeated multipart field `files` to `/api/rest/mva/out/cloud/upload`. Do not send JSON paths or Base64. Require every `data.files[]` item to contain a non-empty `url`; stop before `/make` if any item reports `url=null` or `error`.

Map upload `type`, `url`, and `content_sha256` to make `asset_type`, `asset_url`, and `content_sha256`. Generate an `asset_id` that does not reveal the local absolute path.

### Create and observe a QA task

Send a flat JSON body to `/api/rest/mva/out/cloud/make`. Reuse the same `outer_request_id` after a timeout or ambiguous response. Treat `409102` as adoption of the original task.

Persist `conversation_id`, `outer_request_id`, and `request_id`. Use queryResult for a read-only snapshot and Poll every 3–5 seconds only when active reconciliation is intended. Stop waiting on `completed`, `failed`, or `cancelled`.

### Diagnose Webhooks

Verify the HMAC against the unmodified raw body before parsing JSON. Keep the QA callback secret separate from both QA and production API keys. Deduplicate by `event_id`, acknowledge valid deliveries promptly, and use queryResult for reconciliation.

## Interpret failures

Inspect HTTP status and body `code`; do not branch on `message` text.

- `401100`: QA key missing or invalid. Do not try a production key.
- `403100`: QA key lacks `produce` scope.
- `404100`: verify QA environment, tenant, and `conversation_id`.
- `409102`: idempotent replay; continue with the returned task.
- `409103` or `409104`: terminal failure or cancellation; stop waiting.
- `413100`: reduce upload count, file size, batch size, material count, or tenant usage.
- `422101`: inspect indexed asset errors; no task was created.
- `429100`: honor `Retry-After` and preserve the same `outer_request_id`.
- `500100` or `503xxx`: retain safe trace identifiers and use bounded retry only when the operation remains idempotent.

## Produce a QA evidence report

Report facts and interpretations separately. Include only:

- QA origin and request time with timezone
- endpoint and HTTP method
- `X-Request-ID`
- `outer_request_id` and `conversation_id` when present
- HTTP status, body `code`, task `status`, and `current_node`
- sanitized `data.errors[]`
- whether the request was read-only, uploaded an object, or created/reused a task
- the next bounded diagnostic action

Never include the API key, callback secret, request credential headers, full signed URLs, local absolute paths, or raw media.
