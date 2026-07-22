---
name: cloud-video-production-qa-debugger
description: Diagnose and exercise the Firefly Cloud Video Production public API in the dedicated QA environment at https://medi-qa.fireflyfusion.cn. Use when checking QA gateway health, QA authentication, local image/video direct-to-COS upload, legacy multipart compatibility, Cloud make/poll/queryResult behavior, idempotency, Webhook delivery, error codes, or a known QA conversation_id. Use only the isolated FIREFLY_MVA_QA_API_KEY credential; never use this skill for production, staging, or a customer production key.
---

# Cloud Video Production QA Debugger

Debug the Cloud template-production flow in QA while keeping requests, credentials, identifiers, and evidence isolated from production.

## Load references

- Read `references/qa-debug-playbook.md` before running any QA request.
- Read `references/api-contract.md` before constructing or interpreting direct-upload init/complete, legacy multipart, make, Poll, or queryResult requests.
- Read `references/webhook-contract.md` when diagnosing callbacks or verifying signatures.
- Use `references/openapi.yaml` for schema validation or generated clients.
- Run `scripts/make_from_local_media.py` with `uv run --script` for end-to-end local image/video or mixed-media tasks instead of rebuilding the COS workflow.

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
4. Initialize a direct upload only when the user explicitly selected a local file and the current runtime may read it. Init creates an expiring session and returns temporary credentials; COS upload stores an object even though it does not create a production task. Use legacy multipart only when the user explicitly asks to diagnose that compatibility path.
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

Compute the exact byte size and SHA-256 locally without logging the file content or absolute path.

For every explicitly selected local image or video, regardless of size:

1. Prefer the bundled `scripts/make_from_local_media.py` runner with repeated `--input` values. It accepts images, videos, and mixed inputs.
2. Send basename, size, MIME type, and SHA-256 as flat JSON to `/api/rest/mva/out/cloud/upload/init`.
3. Keep the returned temporary COS credentials in memory only. Do not print, persist, or substitute long-lived COS credentials.
4. Use a Tencent COS SDK high-level transfer API to upload to the exact returned Bucket, Region, and object key with every required header. Let the SDK choose single PUT or multipart/resumable transfer internally; do not add a client-side size branch. File bytes must go directly to COS, not through the QA gateway.
5. After COS reports success, send only `upload_id` to `/api/rest/mva/out/cloud/upload/complete`. Require one non-empty `data.files[]` descriptor before `/make`.

For an intentional QA production, run:

```bash
uv run --script scripts/make_from_local_media.py \
  --input /approved/media/photo.jpg \
  --input /approved/media/clip.mp4 \
  --intent "生成一条节奏明快的短片" \
  --output-dir ./outputs \
  --wait
```

The QA runner refuses a different Base URL, reads only `FIREFLY_MVA_QA_API_KEY`, persists no credentials or signed URLs, and downloads the final video only with `--wait`.

Do not fall back to `/api/rest/mva/out/cloud/upload` when direct upload fails. Use its repeated multipart field `files` only for an explicitly requested legacy-compatibility diagnostic. Do not send JSON paths or Base64. Require every legacy result item to contain a non-empty `url`; stop before `/make` if any item reports `url=null` or `error`.

Map either upload path's `type`, `url`, and `content_sha256` to make `asset_type`, `asset_url`, and `content_sha256`. Generate an `asset_id` that does not reveal the local absolute path.

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
- `404101`: verify the QA `upload_id` and tenant; do not try a production upload session.
- `409102`: idempotent replay; continue with the returned task.
- `409103` or `409104`: terminal failure or cancellation; stop waiting.
- `409105`: the direct-upload session expired; initialize a new object and upload again.
- `413100`: reduce upload count, file size, batch size, material count, or tenant usage.
- `422101`: inspect indexed asset errors or direct-upload size/SHA metadata mismatch; do not call `/make` with an unconfirmed object.
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
- direct `upload_id` and object key only when the QA evidence policy permits them
- whether the request was read-only, uploaded an object, or created/reused a task
- the next bounded diagnostic action

Never include the API key, callback secret, temporary COS credentials, request credential headers, full signed URLs, local absolute paths, or raw media.
