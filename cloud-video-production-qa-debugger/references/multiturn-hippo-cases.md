# Cloud 多轮会话“河马落入泳池”QA 用例

## 1. 目标与边界

核验日期：2026-08-24。

本用例验证 `/api/rest/mva/out/cloud/make` 与 `/poll` 的固定公开会话、多内部 Turn、自然语言续写和并发保护。测试使用一段调用方已获授权、Agent 可访问的现有泳池视频；文档不记录真实素材 URL、API Key、Webhook Secret 或用户素材内容。

固定规则：

- 首轮不传 `conversation_id`，传入素材和用户意图。
- 后续轮复用首轮返回的同一个 `conversation_id`，不再传素材。
- 每个有意创建的新轮次使用新的 `outer_request_id`；同一轮网络重试复用原值。
- `/poll` 始终通过公开 `conversation_id` 返回当前最新内部 Turn。
- 当前 Turn 为 `queued` 或 `running` 时不允许创建下一轮。

## 2. 测试变量

```bash
export MVA_QA_BASE_URL='https://medi-qa.fireflyfusion.cn'
export QA_POOL_VIDEO_URL='<QA_POOL_VIDEO_URL>'
export FIREFLY_MVA_QA_API_KEY='<通过本机密钥管理注入，不写入脚本或文档>'
```

测试意图：

```text
在原视频中加入河马落入泳池、将水溅出并最终让泳池干涸的桥段，生成后下载视频。
```

每次执行前生成唯一的 `qa-` 前缀 `X-Request-ID` 和 `outer_request_id`。以下 JSON 中的标识均为占位符，不要原样并发复用。

## 3. 主链路用例

| 编号 | 当前状态 | 用户输入 | 预期 |
| --- | --- | --- | --- |
| MT-HIPPO-01 | 无会话 | 河马落入泳池原始要求 + 现有泳池视频 | 首轮受理；终态为 `completed + outcome=recommendation + NEED_USER_INPUT`，`video_url` 为空，包含 `GENERATE_SUBJECT` / `GENERATE_ACTION` / `GENERATE_CONTENT` 等不可执行项和素材模板推荐 |
| MT-HIPPO-02 | MT-HIPPO-01 已终态 | `选择第一个`，或明确说出最新返回列表中的一个模板标题 | `/make` 返回相同 `conversation_id`；内部新建 Turn；明确模板选择只命中最新公开推荐，允许本轮 Best-effort 制作；Poll 最终返回视频或明确的模板硬过滤失败 |
| MT-HIPPO-03 | MT-HIPPO-02 已生成视频 | `换一个更轻快、更适合亲子游泳记录的模板` | 接受第三轮且公开 `conversation_id` 不变；不得因为上一轮已经生成视频返回“not waiting for user input”；重新做能力判断和模板匹配 |
| MT-HIPPO-04 | MT-HIPPO-03 已终态 | `改成竖屏，字幕少一点，节奏放慢一些` | 接受下一轮；继承原素材和会话意图；按照本轮明确画幅/风格要求重新执行，Poll 切换到最新 Turn |
| MT-HIPPO-05 | 任一终态 | `还是上一版更好，但音乐更温暖一些` | 接受自然语言修订；不要求客户传 `action`、模板编码、内部 Turn 或历史 state |

### 3.1 首轮提交

```bash
curl --silent --show-error \
  --request POST \
  "${MVA_QA_BASE_URL}/api/rest/mva/out/cloud/make" \
  --header 'Content-Type: application/json' \
  --header "X-API-Key: ${FIREFLY_MVA_QA_API_KEY}" \
  --header 'X-Request-ID: qa-hippo-turn-1-request' \
  --data-binary "$(jq -n \
    --arg url "${QA_POOL_VIDEO_URL}" \
    '{
      user_intent: "在原视频中加入河马落入泳池、将水溅出并最终让泳池干涸的桥段，生成后下载视频。",
      assets: [{
        asset_id: "qa-pool-video-1",
        asset_type: "video",
        asset_url: $url
      }],
      outer_request_id: "qa-hippo-turn-1-<unique>"
    }')"
```

保存返回的 `data.conversation_id` 为 `QA_CONVERSATION_ID`，然后每 3～5 秒 Poll：

```bash
curl --silent --show-error \
  --request POST \
  "${MVA_QA_BASE_URL}/api/rest/mva/out/cloud/poll" \
  --header 'Content-Type: application/json' \
  --header "X-API-Key: ${FIREFLY_MVA_QA_API_KEY}" \
  --header 'X-Request-ID: qa-hippo-poll-turn-1' \
  --data-binary "$(jq -n --arg id "${QA_CONVERSATION_ID}" '{conversation_id: $id}')"
```

### 3.2 后续轮提交

```bash
curl --silent --show-error \
  --request POST \
  "${MVA_QA_BASE_URL}/api/rest/mva/out/cloud/make" \
  --header 'Content-Type: application/json' \
  --header "X-API-Key: ${FIREFLY_MVA_QA_API_KEY}" \
  --header 'X-Request-ID: qa-hippo-turn-2-request' \
  --data-binary "$(jq -n \
    --arg id "${QA_CONVERSATION_ID}" \
    '{
      conversation_id: $id,
      user_intent: "选择第一个",
      outer_request_id: "qa-hippo-turn-2-<unique>"
    }')"
```

后续每轮只替换 `user_intent`、`X-Request-ID` 和 `outer_request_id`；`conversation_id` 始终不变。

## 4. Bad Case

| 编号 | 操作 | 预期 |
| --- | --- | --- |
| MT-HIPPO-B01 | 当前 Turn 仍为 `queued`/`running` 时立即再次 `/make` | HTTP 409、业务码 `409106`；不创建竞争 Turn；继续 Poll 当前轮 |
| MT-HIPPO-B02 | 复用上一轮 `outer_request_id`，但把文字从“选择第一个”改成“选择第二个” | `409106`，提示幂等键被不同续写请求复用；不能把旧键当成新一轮 |
| MT-HIPPO-B03 | 后续轮同时传 `conversation_id` 和 `assets` | HTTP 422、业务码 `400100`；后续轮只能继承素材 |
| MT-HIPPO-B04 | 后续轮 `user_intent` 为空白、对象或缺失 | HTTP 422、业务码 `400100`；后续轮必须是非空自然语言字符串 |
| MT-HIPPO-B05 | 使用不存在、其他租户或其他 `app_id` 的 `conversation_id` | `404100`；不得泄露其他调用方任务是否存在 |
| MT-HIPPO-B06 | 上一轮明确选择模板并生成后，下一轮直接要求“再加一只长颈鹿跳进来” | 必须重新做执行能力判断；历史 `continuation_confirmation` 不得自动继承，本轮不能静默 Best-effort，预期再次返回推荐型终态或明确不可执行反馈 |
| MT-HIPPO-B07 | 用户说出一个不在最新 `template_recommendations` 中的模板编码或模糊标题 | 不得伪造显式模板确认；按普通自然语言修订重新匹配，或在无法解析时返回推荐，不得绕过硬过滤 |
| MT-HIPPO-B08 | 新 Turn 已创建后继续 Poll 同一个公开 ID | Poll 必须返回最新 Turn，而不是缓存上一轮视频结果；运行期状态先变为 `queued/running`，终态再替换结果 |
| MT-HIPPO-B09 | 失败或取消后，使用相同会话但沿用旧 `outer_request_id` | 返回幂等重放/冲突；真正的修订必须使用新的 `outer_request_id` |

## 5. 数据库核验

仅在 QA 数据库使用只读查询；不要在结果中导出 `request_json` 的素材 URL。

```sql
SELECT
    conversation_id AS turn_id,
    cloud_conversation_id,
    cloud_turn_index,
    previous_turn_id,
    status,
    current_node,
    idempotency_key AS outer_request_id,
    created_at,
    completed_at
FROM tasks
WHERE cloud_conversation_id = :conversation_id
ORDER BY cloud_turn_index;
```

验收点：

- 所有行的 `cloud_conversation_id` 相同。
- `cloud_turn_index` 从 1 单调递增，不重复。
- 第 N 轮 `previous_turn_id` 等于第 N-1 轮 `turn_id`。
- B01 不新增行。
- 每个真实新轮次的 `outer_request_id` 唯一。
- `/poll` 响应对应最大 `cloud_turn_index`。

核验历史确认没有泄漏到下一轮：

```sql
SELECT step_name, detail_json
FROM step_records
WHERE conversation_id = :latest_turn_id
  AND step_name IN ('cloud_intent_fusion', 'render_template_matching')
ORDER BY step_order;
```

B06 中 `cloud_intent_fusion` 不应出现由上一轮确认继承而来的 `best_effort_applied=true`。

## 6. 自动化覆盖

本地聚焦测试：

```bash
env PYTHONDONTWRITEBYTECODE=1 \
.venv/bin/python -m pytest -p no:cacheprovider \
  tests/mp_video_agent/test_cloud_continuation.py \
  tests/mp_video_agent/test_cloud_continuation_intent.py \
  tests/mp_video_agent/test_cloud_conversation.py \
  tests/mp_video_agent/test_cloud_production.py \
  tests/mp_video_agent/test_cloud_production_queries.py \
  tests/mp_video_agent/test_cloud_intent.py
```

当前覆盖重点：

- 第二轮视频完成后仍可创建第三轮。
- `queued`/`running` 期间拒绝下一轮。
- `failed`/`cancelled` 后允许在状态和素材可恢复时修订。
- 固定公开 `conversation_id` 与递增内部 Turn。
- 幂等键只允许完全相同请求重放。
- 普通文字不会继承上一轮模板确认。

## 7. QA 通过标准

- 主链路至少完成 MT-HIPPO-01～04。
- Bad Case B01～B06 全部符合预期。
- `/make` 接收响应保持快速，不等待 Graph 或渲染完成。
- `/poll` 只展示最新 Turn，不主动发起新的业务执行。
- 日志、报告和工单不包含 API Key、回调 Secret、完整素材 URL或用户原始视频。
