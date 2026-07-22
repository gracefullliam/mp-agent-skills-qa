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
| 4 | Direct-upload initialization | `POST /api/rest/mva/out/cloud/upload/init` | Creates an expiring QA upload session and issues temporary credentials |
| 5 | Local-material ingestion | COS SDK high-level transfer | Stores objects directly in COS; SDK may use single PUT or multipart |
| 6 | Direct-upload confirmation | `POST /api/rest/mva/out/cloud/upload/complete` | Verifies the object and records usage once |
| 7 | Legacy upload diagnostic, only when requested | `POST /api/rest/mva/out/cloud/upload` | Stores an object through the gateway |
| 8 | End-to-end smoke task | `POST /api/rest/mva/out/cloud/make` | Creates or reuses a task |

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

### Diagnose legacy multipart, only when requested

Do not select this path based on file size and do not use it as a fallback when direct upload fails. When an explicit legacy diagnostic is required, let curl generate the multipart boundary and do not log the command with expanded headers.

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

### Direct-upload every explicitly selected local image or video

Use this path for all new local-material workflows so media bytes bypass the QA gateway:

1. Compute the exact byte count and SHA-256 from the explicitly selected file.
2. Send a flat JSON init request to `https://medi-qa.fireflyfusion.cn/api/rest/mva/out/cloud/upload/init` with a unique `X-Request-ID` and the QA API key.
3. Parse the response in memory. Never print or persist `credentials.tmp_secret_id`, `credentials.tmp_secret_key`, or `credentials.session_token`.
4. Configure a Tencent COS SDK with those temporary credentials and use one high-level transfer call for both images and videos. Upload to the exact returned Bucket, Region, and object key with `part_size_mb`, `Content-Type`, and `x-cos-meta-content-sha256`; let the SDK decide single PUT or multipart internally.
5. Discard the credentials as soon as COS finishes. Send `upload_id` to `/upload/complete`, then require one successful `files[]` descriptor.

Init request body:

```json
{
  "filename": "clip.mp4",
  "size": 1073741824,
  "content_type": "video/mp4",
  "content_sha256": "<64-hex-sha256>"
}
```

Completion is safe to retry after an ambiguous response:

```bash
curl --silent --show-error \
  --request POST \
  'https://medi-qa.fireflyfusion.cn/api/rest/mva/out/cloud/upload/complete' \
  --header 'Content-Type: application/json' \
  --header "X-API-Key: ${FIREFLY_MVA_QA_API_KEY}" \
  --header 'X-Request-ID: qa-debug-upload-complete-001' \
  --data-binary '{"upload_id":"<qa-upload-id>"}'
```

Do not use a generic HTTP PUT unless it implements the exact COS authorization and metadata rules. Do not widen or replace the returned object key. If init returns `404`/`405`, record that the QA service version does not yet expose direct upload; do not fall back to legacy multipart or production for comparison.

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

Do not paste complete upload responses containing temporary credentials or signed URLs into tickets. Prefer in-memory init handling; if a diagnostic tool necessarily writes a restricted response file, delete it immediately after configuring the COS client. Coordinate unused-object and unfinished-multipart cleanup with the QA storage owner after ambiguous upload retries.
