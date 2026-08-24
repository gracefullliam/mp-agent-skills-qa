# Cloud 两轮会话“河马落入泳池”QA 用例

## 1. 目标与边界

核验日期：2026-08-24。

本用例验证 Cloud 成片当前“两轮上限”协议：

- 首轮携带素材和创作意图，不传 `conversation_id`。
- 第二轮只携带首轮固定的 `conversation_id`、自然语言 `user_intent` 和新的 `outer_request_id`，不传素材。
- `/poll` 始终通过固定公开 `conversation_id` 查询当前最新 Turn。
- 当前 Turn 为 `queued` 或 `running` 时拒绝并发续写。
- `CLOUD_MAX_TURNS=2` 时，第二轮终态后拒绝第三轮。
- 测试使用调用方已授权、QA 可访问的泳池视频；文档和报告不记录完整素材 URL、API Key、Webhook Secret 或原始视频内容。

## 2. 公共结果契约

| 结果 | `current_node_description` | 其他要求 |
| --- | --- | --- |
| 首轮推荐完成：`outcome=recommendation` | `已生成可执行方案` | `UNSUPPORTED + NEED_USER_INPUT`、`video_url` 为空、推荐列表非空 |
| 第二轮视频完成：`outcome=video` | `成片创作完成` | `PARTIAL_SUPPORTED + READY`、`video_url` 非空 |
| 第二轮模板匹配运行中 | `正在匹配成片模板...` | 不再展示“成片构想中...” |
| 视频完成且含反馈 | 状态文案与 `feedback.message` 分开展示 | 不做无条件字符串拼接 |

## 3. 测试变量

```bash
export MVA_QA_BASE_URL='https://medi-qa.fireflyfusion.cn'
export QA_POOL_VIDEO_URL='<仅在本机注入，不提交真实 URL>'
export FIREFLY_MVA_QA_API_KEY='<仅在本机密钥管理中注入>'
```

首轮意图：

```text
在原视频中加入河马落入泳池、将水溅出并最终让泳池干涸的桥段，生成后下载视频。
```

每个 HTTP 请求使用唯一的 `qa-` 前缀 `X-Request-ID`。每个真实 Turn 使用新的 `outer_request_id`；同一请求的网络重试复用原值和原 Body。

## 4. 主链路

每个第二轮分支必须从独立的新首轮会话开始，不能在同一会话连续测试多个第二轮选择。

| 编号 | 输入 | 预期 |
| --- | --- | --- |
| MT-HIPPO-01 | 首轮河马意图 + 泳池视频 | 受理后异步完成；`outcome=recommendation`、`UNSUPPORTED`、`NEED_USER_INPUT`、`video_url=""`；`current_node_description=已生成可执行方案`；包含生成类不可执行项和非空模板推荐 |
| MT-HIPPO-02A | 新会话完成 MT-HIPPO-01 后输入 `选择第一个` | 返回相同 `conversation_id`；最终 `PARTIAL_SUPPORTED + READY + outcome=video`；视频 URL 非空；完成文案为“成片创作完成”；不返回推荐列表 |
| MT-HIPPO-02B | 另一新会话完成 MT-HIPPO-01 后输入 `我就是想有个河马` | 返回相同 `conversation_id`；仍明确生成式要求时自动选择最高分可执行模板并 Best-effort 成片；最终视频 URL 非空 |
| MT-HIPPO-02C | 另一新会话完成 MT-HIPPO-01 后输入 `换一个更轻快、更适合亲子游泳记录的模板` | 按普通偏好重新匹配；未形成明确制作授权时可再次返回推荐态；达到两轮上限后不再接受第三次 `/make` |

MT-HIPPO-02B 的反馈必须说明：

- 当前模板成片无法生成素材中不存在的主体、动作或情节；
- 已忽略不可执行部分；
- 已基于现有素材选用最高分可执行模板。

反馈不得出现“第二轮”，也不得重复“完成成片”。

## 5. 请求模板

首轮：

```json
{
  "user_intent": "在原视频中加入河马落入泳池、将水溅出并最终让泳池干涸的桥段，生成后下载视频。",
  "assets": [
    {
      "asset_id": "qa-pool-video-1",
      "asset_type": "video",
      "asset_url": "<QA_POOL_VIDEO_URL>"
    }
  ],
  "outer_request_id": "qa-hippo-turn-1-<unique>"
}
```

第二轮：

```json
{
  "conversation_id": "<固定公开会话 ID>",
  "user_intent": "我就是想有个河马",
  "outer_request_id": "qa-hippo-turn-2-<unique>"
}
```

Poll：

```json
{
  "conversation_id": "<固定公开会话 ID>"
}
```

## 6. Bad Case

| 编号 | 操作 | 预期 |
| --- | --- | --- |
| MT-HIPPO-B01 | 当前 Turn 仍为 `queued/running` 时立即再次 `/make` | HTTP 409、业务码 `409106`；不创建竞争 Turn |
| MT-HIPPO-B02 | 复用已接受 Turn 的 `outer_request_id`，但修改 `user_intent` | HTTP 409、业务码 `409106`；不能把旧幂等键当新 Turn |
| MT-HIPPO-B03 | 后续轮同时传 `conversation_id` 和 `assets` | HTTP 422、业务码 `400100`；不消耗第二轮 |
| MT-HIPPO-B04 | 后续轮 `user_intent` 为空白、对象或缺失 | HTTP 422、业务码 `400100`；不消耗第二轮 |
| MT-HIPPO-B05 | 使用不存在或不属于当前调用方的 `conversation_id` | HTTP 404、业务码 `404100` |
| MT-HIPPO-B06 | 第二轮终态后再次 `/make` | HTTP 409、业务码 `409106`；不新增第三 Turn |
| MT-HIPPO-B07 | 第二轮已创建后继续 Poll 固定公开 ID | 必须返回第二轮运行态或终态，不得缓存首轮推荐结果 |
| MT-HIPPO-B08 | Agent 展示推荐完成态 | 展示“已生成可执行方案”并单独展示 feedback，不显示“成片创作完成” |
| MT-HIPPO-B09 | Agent 展示视频完成态 | 展示“成片创作完成”并单独展示 feedback，不无条件拼接两个字段 |

## 7. 数据库只读核验

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

- 所有 Turn 的 `cloud_conversation_id` 相同。
- `cloud_turn_index` 为 1、2，不重复。
- 第二 Turn 的 `previous_turn_id` 指向第一 Turn。
- B01、B03、B04、B06 不新增 Turn。
- `/poll` 返回最大 `cloud_turn_index` 的结果。

## 8. 本地自动化

```bash
env PYTHONDONTWRITEBYTECODE=1 \
.venv/bin/python -m pytest -p no:cacheprovider \
  tests/mp_video_agent/test_cloud_continuation.py \
  tests/mp_video_agent/test_cloud_continuation_intent.py \
  tests/mp_video_agent/test_cloud_conversation.py \
  tests/mp_video_agent/test_cloud_production.py \
  tests/mp_video_agent/test_cloud_production_queries.py \
  tests/mp_video_agent/test_cloud_intent.py \
  tests/mp_video_agent/test_progress_description.py \
  tests/mp_video_agent/test_cloud_callback_delivery.py
```

覆盖重点：

- 固定公开会话与两内部 Turn；
- 第二轮跳过重复素材理解；
- 模板选择与明确生成式坚持进入 Best-effort；
- 两轮上限、并发与幂等保护；
- Poll、queryResult、Webhook 的推荐/视频完成文案一致。

## 9. 通过标准

- MT-HIPPO-01、02A、02B 通过；
- B01～B06 通过；
- 推荐完成态不再显示“成片创作完成”；
- 视频完成态保留“成片创作完成”，feedback 独立展示；
- `/make` 快速受理，`/poll` 只读取当前最新 Turn；
- 报告不包含凭据、完整素材 URL、签名参数或原始视频。
