# Cloud 多轮会话“河马落入泳池”测试报告

## 1. 报告结论

测试日期：2026-08-24  
测试环境：QA `https://medi-qa.fireflyfusion.cn`  
测试范围：本地多轮逻辑、QA 首轮真实制作、固定 `conversation_id`、幂等重试和后续轮请求校验。

结论：**代码层通过，QA 部署层未通过，当前不能据此验收多轮能力。**

原因不是二次制作业务失败，而是 QA 网关仍运行旧版请求契约：后续请求传入 `conversation_id` 时，QA 仍要求 `assets`，并把 `conversation_id` 判定为未知字段。因此当前 QA 镜像尚未包含固定会话、多 Turn 的公共 API 改动。

## 2. 安全与数据范围

- 只访问固定 QA 域名，没有访问生产。
- 使用环境变量中的 `FIREFLY_MVA_QA_API_KEY`，未读取或输出密钥值。
- 使用已授权的 QA 泳池视频素材；报告不记录完整素材 URL。
- 未启用 Webhook，未接触 Webhook Secret。
- QA 任务已真实创建，属于预期测试副作用。

## 3. 本地自动化结果

执行命令：

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

结果：

```text
117 passed in 1.83s
```

覆盖重点：

- 已完成视频后可以创建下一 Turn。
- `queued`/`running` 时拒绝下一轮。
- `failed`/`cancelled` 后可以在状态可恢复时修订。
- 固定公开 `conversation_id` 和递增内部 Turn。
- 每轮新的 `outer_request_id`，同轮只允许完全一致的重试。
- 历史 `continuation_confirmation` 不会自动变成下一轮授权。

## 4. QA 真实测试记录

### 4.1 网关健康检查

| 项目 | 结果 |
| --- | --- |
| HTTP | `200` |
| 健康状态 | `healthy` |
| 服务版本 | `v2` |
| Apollo | 已启用，刷新无错误 |
| Kafka 日志 | 已连接，未见失败或丢弃 |

### 4.2 首轮河马请求

请求意图：

```text
在原视频中加入河马落入泳池、将水溅出并最终让泳池干涸的桥段，生成后下载视频。
```

| 项目 | 结果 |
| --- | --- |
| HTTP / 业务码 | `200 / 200` |
| 公开会话 | `3244c3a5-b3c1-41d8-b286-9a7918274a97` |
| 首次受理状态 | `running` |
| Poll 轨迹 | `preprocess` → `video_highlight_detection` → `tagging` → `render_template_features` → `render:running` |
| 终态 | `completed` |
| 视频 | `video_url` 非空 |
| 错误 | `error_messages=[]` |
| queryResult | `final_provider=foreign_cloud_edit`，最终渲染状态 `completed` |

观察：当前 QA 首轮直接进入视频制作并返回成片，没有返回预期的 `outcome=recommendation + execution_readiness=NEED_USER_INPUT`。这与本次代码和 QA 用例预期不一致，说明 QA 部署版本的意图融合/推荐阻塞逻辑也不是当前工作区版本。

### 4.3 后续轮请求

请求使用：

- 同一个公开 `conversation_id`
- 不传 `assets`
- 自然语言：`换一个更轻快、更适合亲子游泳记录的模板`
- 新的 `outer_request_id`

QA 返回：

```json
{
  "code": 400100,
  "message": "request validation failed",
  "errors": [
    {
      "field": "assets",
      "reason": "missing",
      "message": "Field required"
    },
    {
      "field": "conversation_id",
      "reason": "extra_forbidden",
      "message": "Extra inputs are not permitted"
    }
  ]
}
```

判定：**QA 尚未部署多轮请求模型。** 这一步在旧版校验层就被拒绝，没有进入 continuation service，也没有创建新 Turn。

### 4.4 幂等重试

使用首轮完全相同的 Body 和 `outer_request_id` 重试：

| 项目 | 结果 |
| --- | --- |
| 业务码 | `409102` |
| `idempotent_replay` | `true` |
| 返回会话 | 与首轮相同 |
| 返回状态 | `completed` |
| 是否新增任务 | 否 |

该项通过。

## 5. 用例通过矩阵

| 用例 | 本地代码 | QA 真实环境 | 结论 |
| --- | --- | --- | --- |
| 首轮接收并异步 Poll | 通过 | 通过 | 通过 |
| 首轮河马需求进入推荐态 | 通过规则测试 | 未进入推荐态 | QA 版本偏旧 |
| 成片后复用会话继续换模板 | 通过 | 被旧请求模型拒绝 | 阻塞 |
| Poll 返回当前最新 Turn | 通过单测 | 尚未产生第二 Turn，无法验收 | 待部署后重测 |
| 运行中抢跑返回 `409106` | 通过单测 | 尚未进入新协议 | 待部署后重测 |
| 幂等键完全一致重试 | 通过 | `409102` | 通过 |
| 幂等键复用但修改意图 | 通过单测 | 受旧请求模型阻塞 | 待部署后重测 |
| 后续轮重复传素材拒绝 | 通过请求模型测试 | 旧版本不支持后续轮字段 | 待部署后重测 |
| 历史 Best-effort 不泄漏到下一轮 | 通过单测 | 尚未产生第二 Turn | 待部署后重测 |

## 6. 当前阻塞与处理建议

### 阻塞证据

QA 返回的 `assets missing + conversation_id extra_forbidden` 与当前工作区的 `CloudProductionRequest` 契约相反。当前代码约定是：首轮带 `assets`，后续轮只带固定 `conversation_id + user_intent + 新 outer_request_id`。

### 下一步

1. 将当前多轮代码构建成 QA 镜像，同时部署 API 和 Worker；不能只重启 API。
2. 确认 QA 的 `/openapi.json` 或部署镜像已出现 `conversation_id` 后续轮字段。
3. 使用新的 QA 会话重新执行 MT-HIPPO-01，不要复用旧会话。
4. 首轮进入 `recommendation + NEED_USER_INPUT` 后执行 MT-HIPPO-02。
5. 第二轮终态后执行 MT-HIPPO-03 和 MT-HIPPO-04。
6. 在任一轮 `running` 时立即发送新一轮，确认 `409106` 且数据库不新增竞争 Turn。
7. 重新执行 B01～B06，并执行数据库只读核验：`cloud_conversation_id` 相同、`cloud_turn_index` 单调递增、`previous_turn_id` 正确。

## 7. 复测通过标准

只有以下条件同时满足，才可以说 QA 多轮需求验收通过：

- 后续 `/make` 不再要求 `assets`。
- 后续 `/make` 接受 `conversation_id`，并返回相同公开会话 ID。
- 每轮创建新的内部 Turn，且 `/poll` 始终返回最新轮。
- `completed` 视频后仍能自然语言换模板或修改要求。
- `queued`/`running` 并发续写返回 `409106`，不产生分叉。
- 历史模板确认不会永久授权新的不可执行要求。
- 幂等重试、坏请求和跨应用隔离仍保持原有错误码契约。
