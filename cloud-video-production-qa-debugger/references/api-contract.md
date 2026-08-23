# Cloud Video Production QA API contract

## Contract summary

All requests in this Skill use the fixed QA origin `https://medi-qa.fireflyfusion.cn` and the prefix `/api/rest/mva/out/cloud`. Do not override the origin or reuse this document for production. All local images and videos use the same direct-to-COS control flow; task and direct-upload control endpoints accept flat JSON. The legacy compatibility upload accepts multipart form data. Successful responses use:

```json
{
  "code": 200,
  "data": {},
  "message": "successful",
  "success": true
}
```

Clients must branch on `code`. `message` is diagnostic text and may change. The first `/make` response creates one fixed public `conversation_id`; every later `/make`, `/poll`, and `/queryResult` reuses that value while the service keeps internal Turn IDs private.

## Authentication and common headers

Use `Content-Type: application/json` for upload init/complete, make, Poll, and queryResult. Use `multipart/form-data` with field name `files` only for the compatibility upload; let the HTTP client generate the multipart boundary.

Send `X-API-Key` from the dedicated `FIREFLY_MVA_QA_API_KEY` environment variable with `produce` scope on every endpoint. Do not read a generic or production credential as a fallback. `X-Request-ID` is optional and traces one HTTP request; it is not an idempotency key.

The QA service operator issues the QA API Key separately from production and transfers the plaintext once through an approved secure channel. Store it in a local secret manager or environment injection mechanism. The public Cloud API does not provide self-registration or plaintext recovery; request a QA-only rotation if the credential is lost or exposed.

## Endpoint matrix

| Method | Path | Purpose | Changes or refreshes task state |
| --- | --- | --- | --- |
| POST | `/api/rest/mva/out/cloud/upload` | Diagnose legacy gateway-proxied multipart upload | Stores media but does not create a production task; not the default local-file path |
| POST | `/api/rest/mva/out/cloud/upload/init` | Issue object-scoped temporary COS credentials for direct multipart upload | Creates an expiring upload session; carries no media bytes |
| POST | `/api/rest/mva/out/cloud/upload/complete` | Verify the COS object and return a make-ready descriptor | Completes upload usage exactly once; creates no production task |
| POST | `/api/rest/mva/out/cloud/make` | Submit the first or a later natural-language Cloud production Turn | Creates an internal Turn unless it is an idempotent replay; the public conversation remains fixed |
| POST | `/api/rest/mva/out/cloud/poll` | Track the current Turn and obtain its terminal result | Resolves and reads the latest persisted internal Turn without starting new work |
| POST | `/api/rest/mva/out/cloud/queryResult` | Read persisted parent-task state and final material | No downstream refresh |

## Diagnose legacy multipart upload

This endpoint remains for old clients and explicit compatibility tests. New Skill workflows must not choose it by file size or use it as an automatic fallback after direct-upload failure.

### Request

```http
POST /api/rest/mva/out/cloud/upload
Content-Type: multipart/form-data
X-API-Key: <server-side-api-key>
```

Send one or more repeated `files` parts. Do not send Base64, JSON file paths, or a `content` envelope. The caller must run in a trusted environment that can read the user-selected file; browser and mobile clients must not receive the API key.

The environment configures allowed extensions, maximum file count, per-file size, total batch size, and optional tenant daily/monthly quotas. The current implementation buffers each accepted file in Agent memory before writing it to COS/OSS, so keep this temporary path to bounded files and batches.

### Response

```json
{
  "code": 200,
  "data": {
    "files": [
      {
        "filename": "pet.mp4",
        "url": "https://cdn.example.com/uploads/pet.mp4",
        "type": "video",
        "size": 12345678,
        "content_sha256": "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef"
      }
    ]
  },
  "message": "successful",
  "success": true
}
```

Map `type` to `asset_type`, `url` to `asset_url`, and `content_sha256` to the same-named `/make` field. Do not expose a local absolute path as `asset_id` or metadata.

The endpoint can return HTTP 200 with per-file partial failures:

```json
{
  "filename": "broken.mp4",
  "url": null,
  "type": "video",
  "error": "upload failed"
}
```

Require every requested file to have a non-empty `url`; do not start production from an incomplete batch. The upload endpoint has no idempotency key. Retrying an ambiguous timeout can create an unused stored object.

## Upload all local materials directly to COS

### Initialize

For every local image or video, compute file size and SHA-256 locally, then send metadata only. Do not branch on file size:

```http
POST /api/rest/mva/out/cloud/upload/init
Content-Type: application/json
X-API-Key: <qa-api-key>
X-Request-ID: qa-direct-upload-init-001
```

```json
{
  "filename": "pet.mp4",
  "size": 1073741824,
  "content_type": "video/mp4",
  "content_sha256": "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef"
}
```

`filename` must be a basename with an allowed extension, not a local path. `size` is the exact positive byte count. `content_sha256` is required and contains 64 hexadecimal characters. Unknown fields are rejected.

The response contains control data and short-lived credentials, never media bytes:

```json
{
  "code": 200,
  "data": {
    "upload_id": "43a6df89-c48d-4a71-9a71-95013a4109b5",
    "upload_mode": "cos_sts_multipart",
    "bucket": "qa-media-1250000000",
    "region": "ap-shanghai",
    "object_key": "uploads/direct/0123456789abcdef/20260722/43a6df89-c48d-4a71-9a71-95013a4109b5.mp4",
    "part_size_mb": 16,
    "credentials": {
      "tmp_secret_id": "<temporary>",
      "tmp_secret_key": "<temporary>",
      "session_token": "<temporary>"
    },
    "start_time": 1784700000,
    "expired_time": 1784703600,
    "required_headers": {
      "Content-Type": "video/mp4",
      "x-cos-meta-content-sha256": "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef"
    },
    "request_id": "qa-direct-upload-init-001"
  },
  "message": "successful",
  "success": true
}
```

Configure a Tencent COS SDK client with `tmp_secret_id`, `tmp_secret_key`, `session_token`, and `region`. Use one high-level transfer workflow for images and videos; the SDK may choose single PUT or multipart internally according to `part_size_mb`. Upload directly to the exact returned `bucket/object_key` with all `required_headers`. Do not change the object key, reuse the credentials for another object, persist credentials, print them, or fall back to gateway multipart. File bytes travel from the QA client to COS, not to `https://medi-qa.fireflyfusion.cn`.

### Complete

After the COS SDK reports successful multipart completion, send:

```http
POST /api/rest/mva/out/cloud/upload/complete
Content-Type: application/json
X-API-Key: <qa-api-key>
```

```json
{
  "upload_id": "43a6df89-c48d-4a71-9a71-95013a4109b5"
}
```

The service verifies the object using COS `HEAD Object`, including exact `Content-Length` and `x-cos-meta-content-sha256`, then returns the same `files[]` descriptor shape as the compatibility upload:

```json
{
  "code": 200,
  "data": {
    "upload_id": "43a6df89-c48d-4a71-9a71-95013a4109b5",
    "status": "completed",
    "files": [{
      "filename": "pet.mp4",
      "url": "https://cdn.example.com/uploads/direct/pet.mp4",
      "type": "video",
      "size": 1073741824,
      "content_sha256": "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef"
    }],
    "request_id": "qa-direct-upload-init-001"
  },
  "message": "successful",
  "success": true
}
```

Repeat completion safely after an ambiguous response; a completed session does not double-count usage. A `404101` means the upload session is unknown to this QA tenant. A `409105` means it expired; initialize a new object and upload again. A `422101` means the COS object is absent or its size/SHA metadata does not match; do not call `/make`.

## Submit a production Turn

### Request

```http
POST /api/rest/mva/out/cloud/make
```

```json
{
  "user_intent": "生成一条节奏明快的宠物日常短片",
  "assets": [
    {
      "asset_id": "asset-video-001",
      "asset_type": "video",
      "asset_url": "https://cdn.example.com/media/pet-001.mp4",
      "duration_sec": 18.6,
      "width": 1080,
      "height": 1920
    }
  ],
  "outer_request_id": "customer-order-20260719-001"
}
```

### Top-level fields

| Field | Type | Required | Contract |
| --- | --- | --- | --- |
| `conversation_id` | string | Later Turns only | Omit on the first Turn. Persist the first response value and reuse the same fixed ID on every later Turn |
| `user_intent` | string or object | Conditional | Optional text/object on the first Turn; a non-blank text string is required on later Turns; text is trimmed and truncated to 200 Unicode characters |
| `assets` | array | First Turn only | At least one item on the first Turn; omit on later Turns because the service inherits source materials |
| `outer_request_id` | string | No | Customer-generated idempotency identifier, unique within the customer's tenant |
| `callback_url` | URL | First Turn only | Public HTTPS Webhook endpoint |
| `callback_events` | string[] | First Turn only | Requires `callback_url`; defaults to the three terminal events when omitted |

### `assets[]` fields

| Field | Type | Required | Contract |
| --- | --- | --- | --- |
| `asset_id` | string | No | Stable and unique within one request; generated as `A001`, `A002`, ... when missing or blank |
| `asset_type` | `image` or `video` | Yes | Must agree with a recognizable URL extension |
| `asset_url` | HTTP/HTTPS URL | Yes | Must be reachable by the service and return matching media content; may come from the Cloud upload endpoint |
| `content_sha256` | string | No | Exactly 64 hexadecimal characters; used for content deduplication |
| `duration_sec` | number >= 0 | No | Video duration in seconds; recommended for video |
| `width` | integer > 0 | No | Original width in pixels |
| `height` | integer > 0 | No | Original height in pixels |
| `metadata` | object | No | Customer business metadata; not a channel for templates, highlights, or preprocessing output |

The API accepts no field aliases. In particular, reject `materials`, `item_list`, `material_type`, `source_uri`, `asset_uri`, `url`, `outerRequestId`, `callbackUrl`, and `callbackEvents`.

The service validates asset accessibility before creating a conversation. A rejected first-Turn asset returns `422101` and no `conversation_id`.

### Accepted response

```json
{
  "code": 200,
  "data": {
    "conversation_id": "43a6df89-c48d-4a71-9a71-95013a4109b5",
    "status": "queued",
    "request_id": "customer-trace-001",
    "outer_request_id": "customer-order-20260719-001"
  },
  "message": "successful",
  "success": true
}
```

`status` may initially be `queued` or `running`. When `outer_request_id` was omitted, the response omits it. A later-Turn response repeats the first Turn's fixed `conversation_id`; only the internal Turn changes.

### Idempotent replay

```json
{
  "code": 409102,
  "data": {
    "conversation_id": "43a6df89-c48d-4a71-9a71-95013a4109b5",
    "status": "running",
    "idempotent_replay": true,
    "outer_request_id": "customer-order-20260719-001"
  },
  "message": "outer_request_id already exists; returning existing task",
  "success": false
}
```

Although `success` is false, this response identifies the existing accepted Turn. Continue tracking that fixed `conversation_id`.

## Poll a production

### Request

```http
POST /api/rest/mva/out/cloud/poll
```

```json
{
  "conversation_id": "43a6df89-c48d-4a71-9a71-95013a4109b5"
}
```

Poll every 3–5 seconds. Stop after a terminal state or when the customer cancels its local wait.

### Running response

```json
{
  "code": 200,
  "data": {
    "conversation_id": "43a6df89-c48d-4a71-9a71-95013a4109b5",
    "status": "running",
    "current_node": "render_template_matching",
    "current_node_description": "成片构想中...",
    "error_messages": []
  },
  "message": "successful",
  "success": true
}
```

`current_node` is a machine key. Display `current_node_description` to end users.

### Completed response

```json
{
  "code": 200,
  "data": {
    "conversation_id": "43a6df89-c48d-4a71-9a71-95013a4109b5",
    "status": "completed",
    "current_node": "completed",
    "current_node_description": "成片创作完成",
    "video_url": "https://result.example.com/final.mp4",
    "error_messages": []
  },
  "message": "successful",
  "success": true
}
```

Poll is the customer-facing current-Turn result. For `outcome=video`, it returns the final `video_url`; for `outcome=recommendation`, it returns the feedback and recommendation fields without a video.

### Recommendation completion and continuation

When `outcome=recommendation` and `execution_readiness=NEED_USER_INPUT`, present `feedback`, `recommendations`, and `template_recommendations`, then forward the user's next message unchanged:

```json
{
  "conversation_id": "43a6df89-c48d-4a71-9a71-95013a4109b5",
  "user_intent": "选择第一个",
  "outer_request_id": "qa-customer-order-turn-2"
}
```

The same protocol also applies after a completed video, failure, or cancellation. The user may keep changing templates, style, pacing, copy, aspect ratio, or another video-production requirement. The service accepts a later Turn only when the current Turn is `completed`, `failed`, or `cancelled`; `queued`/`running` concurrency returns `409106`. Every intentional Turn uses a new `outer_request_id`, while an ambiguous retry of the same Turn reuses the same value and body.

### Failed response

Production failure returns HTTP 409 with code `409103`; cancellation returns code `409104`. Both end only the current Turn and include the fixed conversation identifier, terminal status, current-node fields, and `error_messages`.

## Query the parent task

### Request

```http
POST /api/rest/mva/out/cloud/queryResult
```

```json
{
  "conversation_id": "43a6df89-c48d-4a71-9a71-95013a4109b5"
}
```

This endpoint reads persisted parent-task state and does not refresh the downstream renderer. It does not aggregate internal node inputs or outputs.

When the parent task is completed, `data` additionally contains:

```json
{
  "final_video_result": {
    "status": "completed",
    "render_task_id": "<provider-business-id>",
    "provider_task_id": "<provider-task-id>",
    "video_url": "https://result.example.com/final.mp4",
    "poster_url": "https://result.example.com/poster.jpg",
    "preview_url": "https://result.example.com/final.mp4",
    "error_message": "",
    "provider": "foreign_cloud_edit"
  },
  "video_url": "https://result.example.com/final.mp4",
  "poster_url": "https://result.example.com/poster.jpg"
}
```

`poster_url` may be empty when the renderer does not return a poster.

## Error codes

| Code | Meaning | Client action |
| ---: | --- | --- |
| `400100` | Request or upload validation failed | Fix JSON, required fields, multipart field name, file type, field names, or extra fields; inspect `data.errors[]` when present |
| `401100` | Authentication required | Supply or rotate the server-side API key |
| `403100` | Permission denied | Ensure the key has `produce` scope |
| `404100` | Task not found | Verify `conversation_id`, environment, and tenant |
| `404101` | Direct upload session not found | Verify QA `upload_id` and tenant; initialize again when necessary |
| `405100` | Method not allowed | Use the documented HTTP method |
| `409100` | `outer_request_id` belongs to another flow | Use the correct business identifier or create a new intended request |
| `409101` | Callback configuration differs on replay | Reuse the original callback configuration |
| `409102` | Idempotent replay | Adopt the returned existing task |
| `409103` | Production failed | Stop waiting; retain task identifiers and errors for support |
| `409104` | Production cancelled | Stop waiting |
| `409105` | Direct upload session expired | Initialize a new object-scoped QA upload and upload again |
| `409106` | Later-Turn request conflicts with the active conversation or reused idempotency key | Continue Poll if the current Turn is active; otherwise correct the fixed conversation, user text, or idempotency key without blind retry |
| `413100` | Input or upload limit exceeded | Reduce asset count, upload file count, file size, total batch size, or tenant usage |
| `422100` | Invalid callback URL | Use an allowed public HTTPS endpoint |
| `422101` | Asset unavailable | Fix the indexed asset using `data.errors[]` |
| `429100` | Rate limited | Honor `Retry-After` and retry with the same `outer_request_id` |
| `500100` | Internal error | Retain trace identifiers; use a bounded retry only when the operation is idempotent |
| `503100` | Callback service unavailable | Omit callback and use Poll, or retry later |
| `503101` | Dependency unavailable | Retry with bounded backoff and the same `outer_request_id` |

Validation details use one shape:

```json
{
  "errors": [
    {
      "field": "assets.0.asset_url",
      "reason": "http_status",
      "message": "asset is unavailable",
      "asset_id": "asset-video-001",
      "http_status": 404
    }
  ]
}
```
