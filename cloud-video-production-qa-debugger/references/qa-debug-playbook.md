# QA debug playbook

## Contents

- Environment boundary
- Credential preflight
- Diagnostic sequence
- Safe request templates
- Evidence and cleanup

## Environment boundary

Use only:

```text
QA origin: https://medi-qa.fireflyfusion.cn
QA key variable: FIREFLY_MVA_QA_API_KEY
Cloud prefix: /api/rest/mva/out/cloud
```

Do not accept a caller-provided override for the QA origin. Do not look for `API_KEY`, `X_API_KEY`, `FIREFLY_API_KEY`, `FIREFLY_MVA_PROD_API_KEY`, or another fallback credential.

## Credential preflight

Confirm the dedicated QA key exists without printing it:

```bash
if test -z "${FIREFLY_MVA_QA_API_KEY:-}"; then
  echo "FIREFLY_MVA_QA_API_KEY is not configured" >&2
  exit 1
fi
```

Never enable shell tracing. Never use verbose HTTP output because it can expose request headers.

## Diagnostic sequence

| Order | Check | Endpoint | Side effect |
| ---: | --- | --- | --- |
| 1 | Gateway health | `GET /api/rest/mva/health` | None |
| 2 | Known task snapshot | `POST /api/rest/mva/out/cloud/queryResult` | Reads persisted state |
| 3 | Renderer reconciliation | `POST /api/rest/mva/out/cloud/poll` | May refresh render state |
| 4 | Local-material ingestion | `POST /api/rest/mva/out/cloud/upload` | Stores objects |
| 5 | End-to-end smoke task | `POST /api/rest/mva/out/cloud/make` | Creates or reuses a task |

Stop after the first layer that explains the failure. Do not create a task merely to diagnose a gateway, credential, or known-task problem.

## Safe request templates

### Health

```bash
curl --silent --show-error \
  'https://medi-qa.fireflyfusion.cn/api/rest/mva/health'
```

### Query a known task

Replace the placeholder with a QA `conversation_id`. Do not use a production identifier.

```bash
curl --silent --show-error \
  --request POST \
  'https://medi-qa.fireflyfusion.cn/api/rest/mva/out/cloud/queryResult' \
  --header 'Content-Type: application/json' \
  --header "X-API-Key: ${FIREFLY_MVA_QA_API_KEY}" \
  --header 'X-Request-ID: qa-debug-query-001' \
  --data-binary '{"conversation_id":"<qa-conversation-id>"}'
```

### Poll a known task

```bash
curl --silent --show-error \
  --request POST \
  'https://medi-qa.fireflyfusion.cn/api/rest/mva/out/cloud/poll' \
  --header 'Content-Type: application/json' \
  --header "X-API-Key: ${FIREFLY_MVA_QA_API_KEY}" \
  --header 'X-Request-ID: qa-debug-poll-001' \
  --data-binary '{"conversation_id":"<qa-conversation-id>"}'
```

### Upload explicitly selected files

Let curl generate the multipart boundary. Do not log the command with expanded headers.

```bash
curl --silent --show-error \
  --request POST \
  'https://medi-qa.fireflyfusion.cn/api/rest/mva/out/cloud/upload' \
  --header "X-API-Key: ${FIREFLY_MVA_QA_API_KEY}" \
  --header 'X-Request-ID: qa-debug-upload-001' \
  --form 'files=@/approved/workspace/clip.mp4' \
  --form 'files=@/approved/workspace/cover.jpg'
```

Store the full response only in a restricted temporary location when signed URLs are returned. Inspect a sanitized projection for evidence. Require every file item to have a URL before constructing `/make` input.

### Create a QA task

Use a new `qa-`-prefixed `outer_request_id` only for an intentional new smoke test. Reuse it for ambiguous retries.

```bash
curl --silent --show-error \
  --request POST \
  'https://medi-qa.fireflyfusion.cn/api/rest/mva/out/cloud/make' \
  --header 'Content-Type: application/json' \
  --header "X-API-Key: ${FIREFLY_MVA_QA_API_KEY}" \
  --header 'X-Request-ID: qa-debug-make-001' \
  --data-binary '{
    "user_intent": "QA smoke test",
    "assets": [
      {
        "asset_id": "qa-asset-001",
        "asset_type": "video",
        "asset_url": "<qa-accessible-media-url>"
      }
    ],
    "outer_request_id": "qa-debug-<stable-unique-id>"
  }'
```

## Evidence and cleanup

Capture request time, endpoint, safe trace identifiers, HTTP status, body code, task status, current node, and sanitized errors. Record whether the action stored media or created a task.

Do not paste complete upload responses containing signed URLs into tickets. Remove restricted temporary response files after extracting the required URL into the immediate QA request flow. Coordinate unused-object cleanup with the QA storage owner after ambiguous upload retries.
