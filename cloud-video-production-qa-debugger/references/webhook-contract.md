# Cloud production QA Webhook contract

Use a QA-only callback endpoint and a QA-only signing secret. Store the signing secret separately from `FIREFLY_MVA_QA_API_KEY`; never reuse a production callback secret. When an environment variable is required, use `FIREFLY_MVA_QA_WEBHOOK_SECRET` without a generic or production fallback.

## Subscription

Include a public HTTPS `callback_url` in the create request. `callback_events` is optional.

Default events when `callback_events` is omitted:

- `production.completed`
- `production.failed`
- `production.cancelled`

Supported events:

- `input.validated`
- `intent.completed`
- `highlight.completed`
- `material_analysis.completed`
- `template_match.completed`
- `render.submitted`
- `production.completed`
- `production.failed`
- `production.cancelled`

Changing the callback URL or event set during an `outer_request_id` replay returns `409101`.

## Delivery

```http
Content-Type: application/json
X-MP-Video-Event: production.completed
X-MP-Video-Delivery: d3acb895-13bd-4710-ab06-90623fce85d2
X-MP-Video-Timestamp: 1784450000
X-MP-Video-Signature: sha256=<hex-digest>
```

```json
{
  "event": "production.completed",
  "event_id": "d3acb895-13bd-4710-ab06-90623fce85d2",
  "conversation_id": "43a6df89-c48d-4a71-9a71-95013a4109b5",
  "request_id": "customer-trace-001",
  "status": "completed",
  "current_node": "completed",
  "current_node_description": "成片创作完成",
  "occurred_at": "2026-07-19T08:30:00+00:00",
  "data": {
    "video_url": "https://result.example.com/final.mp4"
  }
}
```

`current_node` is the stable machine-readable progress key. `current_node_description` is the corresponding Chinese progress copy and uses the same mapping as Poll/queryResult. Intermediate event `data` is currently empty. `production.completed` exposes only `video_url` in `data`; it does not expose `poster_url`.

## Signature verification

The signing input is:

```text
<X-MP-Video-Timestamp>.<raw_request_body>
```

Compute HMAC-SHA256 with the shared callback secret and compare the lowercase hex digest with the value after `sha256=` using a constant-time comparison.

Verification order:

1. Read the raw request bytes before JSON parsing.
2. Require the four `X-MP-Video-*` headers.
3. Reject a timestamp outside the customer's allowed clock-skew window.
4. Compute and compare the signature in constant time.
5. Parse the JSON only after signature verification.
6. Deduplicate by `event_id`; the delivery header carries the same identifier.

Never reserialize JSON before signature verification because whitespace and key order affect the digest.

## Delivery behavior

- Return any 2xx after the event has been durably accepted.
- Handle business work asynchronously so the receiver responds quickly.
- Non-2xx responses, timeouts, and network errors are retried with bounded exponential backoff.
- Assume duplicate delivery and make processing idempotent.
- Do not assume events from separate tasks arrive in global order.
- Treat Webhook as notification. Use `queryResult` for reconciliation when local state is missing or ambiguous.
- A callback delivery failure does not change the Cloud production task result.

## Receiver checklist

- HTTPS endpoint is publicly reachable by the Agent service.
- Callback secret is stored in a secret manager.
- Raw-body capture occurs before framework JSON middleware mutates the body.
- Signature and timestamp are verified.
- `event_id` is stored with a unique constraint or equivalent idempotency guard.
- Receiver returns 2xx only after durable acceptance.
- Processing tolerates duplicate and out-of-order events.
- Operational logs include `event_id`, `conversation_id`, event, and status, but not the secret or signature input.

## Agent self-receiver for QA

QA can use the Agent service's own signed receiver when a customer endpoint is not ready:

```text
https://mp-video-agent-qa.fireflyfusion.cn/api/rest/mva/webhook
```

It applies the production HMAC contract and five-minute timestamp window, logs the callback payload, returns an acknowledgement, and performs no task mutation. It is a connectivity/signature probe, not a customer-side persistence or reconciliation substitute.
