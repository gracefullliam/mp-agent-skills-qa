---
name: cloud-video-production-qa-debugger
description: Exercise the Firefly Cloud Video Production public API from a user perspective in the dedicated QA environment at https://medi-qa.fireflyfusion.cn. Use when checking QA reachability and authentication, uploading explicitly selected local image/video media, creating and polling a Cloud task, continuing a conversation with natural-language revisions, or diagnosing a QA request the operator describes. Use only the isolated FIREFLY_MVA_QA_API_KEY credential; never use this skill for production, staging, or a customer production key.
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
2. For a known `conversation_id`, call `POST /api/rest/mva/out/cloud/queryResult` first when inspecting persisted parent-task projections.
3. Use `POST /api/rest/mva/out/cloud/poll` to verify the customer-facing current-turn status and result. Poll reads the latest persisted Turn and does not start new business work.
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

The first `/make` response creates one fixed public `conversation_id`. After the current internal Turn reaches `completed`, `failed`, or `cancelled`, submit the user's next natural-language revision to the same `/make` endpoint with that fixed ID, no `assets`, and a new `outer_request_id`. A completed video does not close the conversation. Do not create the next Turn while the current one is `queued` or `running`; expect `409106` and continue Poll instead.

### User-facing interaction policy

默认按正式产品的用户心智执行，不按预设测试脚本连续跑多轮：

- 首轮只接收用户提供的素材和自然语言意图，等待当前 Turn 结束后返回结果。
- 首轮得到推荐或 `NEED_USER_INPUT` 时，只展示推荐结果、固定 `conversation_id` 和下一步提示，然后停止；不要因为存在推荐结果就自动发送第二轮。
- 用户下一次明确表达新意图后，才继续同一个 Cloud 会话。内部自动复用固定 `conversation_id`、生成新的 `outer_request_id`，并且不要求用户提供 Turn、任务 ID 或内部状态。
- 不把 HTTP 请求体、业务 code 或数据库字段暴露给普通用户；这些只在用户要求诊断或生成报告时使用。
- 只有用户明确要求一次性执行多轮或自动化测试时，才允许在一次 Codex 任务中连续发送后续轮次；执行前先告知将自动创建几轮。

当用户只要求一次冒烟测试时，执行计划必须明确“首轮完成后停止，等待用户下一条消息”，不得自动发起第二个 `/make`。

### User-visible error handling

把典型错误转换成用户能理解的下一步，不把堆栈、数据库字段或内部 Turn 暴露给用户。业务控制以 HTTP 状态、响应 `code` 和当前任务状态为准；服务端 `message` 只作为脱敏后的解释，不要用字符串匹配代替状态判断。

| HTTP / `code` | 用户看到的情况 | 处理方式 |
| --- | --- | --- |
| `401100` / `403100` | QA 未授权或 Key 没有 `produce` 权限 | 停止请求，提示 QA 鉴权配置问题；不尝试生产 Key |
| `404100` | 会话不存在、已过期或当前调用方不可见 | 提示无法找到当前会话；不要泄露其他调用方任务是否存在 |
| `409102` | 网络重试导致同一请求被重复提交 | 继续使用服务端返回的原任务，不创建新任务 |
| `409106`（当前 Turn 仍在 `queued`/`running`） | “当前会话正在处理，请稍后查看结果” | 不再次 `/make`，继续 Poll 当前 `conversation_id` |
| `409106`（服务端明确提示达到最大轮次） | “当前会话已达到最大修改次数，请重新开始” | 停止当前续写；保留旧会话查询能力，新需求新建会话 |
| `409103` / `409104` | 当前成片任务失败或已取消 | 展示简短失败原因；停止当前等待，不做无界重试 |
| `409105` | 上传会话已过期 | 重新初始化上传并重新提交素材 |
| `413100` / `422101` | 素材数量、大小、格式或校验信息不符合要求 | 指出需要修正素材，不要直接重试同一请求 |
| `429100` | 请求过于频繁 | 遵守 `Retry-After`；相同请求继续复用原 `outer_request_id` |
| `500100` / `503xxx` | QA 服务暂时异常 | 仅对仍具幂等性的请求做有限重试，并保留原始请求标识 |

正常响应也要按用户状态解释：推荐态返回“已生成可执行方案，请告诉我下一步怎么调整”，视频完成返回“成片创作完成”；不要把 `current_node_description` 和 `feedback.message` 无条件拼成一段话。

推荐结果中的 `template_recommendations` 必须面向用户展示为简洁列表。每一项只展示模板标题和公开的预览链接；服务端字段 `preview_url`（如内部对象映射为 `previewUrl`）只用于读取地址，绝不能作为用户可见的链接文字或标签。链接文字必须固定为“点击查看模板效果”，例如：

```markdown
### 可选模板

1. **全力以赴的快乐** — [点击查看模板效果](https://example.com/template-preview.mp4)
2. **小棉袄** — [点击查看模板效果](https://example.com/template-preview-2.mp4)
```

不要只说“模板候选包括……”，也不要把 `template_code`、内部评分、数据库字段、`preview_url` 或 `previewUrl` 标签塞进普通用户列表。`preview_url` 为空时不生成假链接，保留标题并标注“暂无预览”。只有用户明确要求原始接口字段时，才额外返回 `title` 和 `previewUrl` 的字段值；默认用户展示仍使用“点击查看模板效果”。

用户要求更多模板时，继续使用同一会话提交原话；返回新批次后仍只展示标题和“点击查看模板效果”，并等待用户下一步。

If the user asks for more templates or more recommendations (for example, “再给一些模板”“这些都不满意”“还有别的吗”), forward the original text as a new Turn with the fixed `conversation_id`, no `assets`, and a new `outer_request_id`. The service classifies the request as `request_more_templates` and uses its recommendation cache to avoid previously exposed templates. Do not choose a template, upload media, or construct candidates locally for this action. Repeat only while the service accepts the continuation; do not impose a local two-turn limit.

Every later user instruction—including a template ordinal/title, a repeated unsupported generation request, or a change after a completed video—must be submitted as a later Turn on the fixed `conversation_id`. Never create a new first-turn task to apply a template or “try again”: doing so loses the source materials and recommendation batch and can silently produce the same default template. Forward ordinal text such as `1`, `2`, or `3` unchanged. If the server rejects a reference because it was not in the current recommendation batch, report that conflict and ask the operator to choose from the returned list; do not locally resolve it or start a new conversation.

### Diagnose Webhooks

Verify the HMAC against the unmodified raw body before parsing JSON. Keep the QA callback secret separate from both QA and production API keys. Deduplicate by `event_id`, acknowledge valid deliveries promptly, and use queryResult for reconciliation.

## Interpret failures

Inspect HTTP status and body `code`; do not branch on `message` text.

- `401100`: QA key missing or invalid. Do not try a production key.
- `403100`: QA key lacks `produce` scope.
- `404100`: verify QA environment, tenant, and `conversation_id`.
- `404101`: verify the QA `upload_id` and tenant; do not try a production upload session.
- `409102`: idempotent replay; continue with the returned task.
- `409103` or `409104`: terminal failure or cancellation; stop the current wait. A later natural-language revision may reuse the fixed conversation with a new `outer_request_id`.
- `409105`: the direct-upload session expired; initialize a new object and upload again.
- `409106`: the current Turn is still active, the conversation/application does not match, or an idempotency key was reused with different text. Continue Poll for an active Turn; otherwise fix the request without blind retry.
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
