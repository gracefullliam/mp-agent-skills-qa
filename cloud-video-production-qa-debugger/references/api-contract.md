# Cloud Video Production QA API contract

## Contract summary

All requests in this Skill use the fixed QA origin `https://medi-qa.fireflyfusion.cn` and the prefix `/api/rest/mva/out/cloud`. Do not override the origin or reuse this document for production. Task and direct-upload control endpoints accept flat JSON; the small-file compatibility upload accepts multipart form data. Successful responses use:

```json
{
  "code": 200,
  "data": {},
  "message": "successful",
  "success": true
}
```

Clients must branch on `code`. `message` is diagnostic text and may change.

## Authentication and common headers

Use `Content-Type: application/json` for upload init/complete, make, Poll, and queryResult. Use `multipart/form-data` with field name `files` only for the compatibility upload; let the HTTP client generate the multipart boundary.

Send `X-API-Key` from the dedicated `FIREFLY_MVA_QA_API_KEY` environment variable with `produce` scope on every endpoint. Do not read a generic or production credential as a fallback. `X-Request-ID` is optional and traces one HTTP request; it is not an idempotency key.

The QA service operator issues the QA API Key separately from production and transfers the plaintext once through an approved secure channel. Store it in a local secret manager or environment injection mechanism. The public Cloud API does not provide self-registration or plaintext recovery; request a QA-only rotation if the credential is lost or exposed.

## Endpoint matrix

| Method | Path | Purpose | Changes or refreshes task state |
| --- | --- | --- | --- |
| POST | `/api/rest/mva/out/cloud/upload` | Upload local image/video files and return make-ready URLs | Stores media but does not create a production task |
| POST | `/api/rest/mva/out/cloud/upload/init` | Issue object-scoped temporary COS credentials for direct multipart upload | Creates an expiring upload session; carries no media bytes |
| POST | `/api/rest/mva/out/cloud/upload/complete` | Verify the COS object and return a make-ready descriptor | Completes upload usage exactly once; creates no production task |
| POST | `/api/rest/mva/out/cloud/make` | Create an asynchronous Cloud production | Creates a task unless it is an idempotent replay |
| POST | `/api/rest/mva/out/cloud/poll` | Track progress and actively obtain terminal video status | May refresh downstream render status |
| POST | `/api/rest/mva/out/cloud/queryResult` | Read persisted parent-task state and final material | No downstream refresh |

## Upload local materials

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

## Upload large materials directly to COS

### Initialize

Compute file size and SHA-256 locally, then send metadata only:

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

Configure a Tencent COS SDK client with `tmp_secret_id`, `tmp_secret_key`, `session_token`, and `region`. Upload the selected local file directly to the exact returned `bucket/object_key`, using `part_size_mb` and all `required_headers`. Do not change the object key, reuse the credentials for another object, persist credentials, or print them. File bytes travel from the QA client to COS, not to `https://medi-qa.fireflyfusion.cn`.

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

## Create a production

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
| `user_intent` | string or object | No | Text, or `{ "text": string, "speech_url": string }`; text is trimmed and truncated to 200 Unicode characters |
| `assets` | array | Yes | At least one item; the environment may impose an upper limit |
| `outer_request_id` | string | No | Customer-generated idempotency identifier, unique within the customer's tenant |
| `callback_url` | URL | No | Public HTTPS Webhook endpoint |
| `callback_events` | string[] | No | Requires `callback_url`; defaults to the three terminal events when omitted |

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

The service validates asset accessibility before creating a task. A rejected asset returns `422101` and no `conversation_id`.

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

`status` may initially be `queued` or `running`. When `outer_request_id` was omitted, the response omits it.

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

Although `success` is false, this response identifies the existing accepted task. Continue tracking that `conversation_id`.

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

The current Poll contract returns the final `video_url`. Use `queryResult` for the detailed final material and poster projection.

### Failed response

Production failure returns HTTP 409 with code `409103`; cancellation returns code `409104`. Both include the task identifier, terminal status, current-node fields, and `error_messages`.

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
