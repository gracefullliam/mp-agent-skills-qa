# Cloud 两轮“河马落入泳池”测试报告

## 1. 结论

测试日期：2026-08-24  
本地代码：`/Users/yulin/code/mp-video-agent`，分支 `Lynn-Refeactor`
QA 环境：`https://medi-qa.fireflyfusion.cn`

结论：

- **本地自动化通过**：Cloud 两轮、意图融合、Poll/queryResult/Webhook 投影和进度文案共 159 项通过。
- **QA 新版本验收阻塞**：执行期间确认本次代码尚未部署到 QA，因此不能把远端旧版本结果判定为新代码失败。
- **QA 旧版本基线已确认**：健康检查正常；已有会话的 Poll 仍缺少 `outcome`、`intent_support_status`、`execution_readiness` 等新投影，并把无视频完成态显示为“成片创作完成”。
- **推荐完成文案已在本地修复**：`outcome=recommendation` 使用“已生成可执行方案”；`outcome=video` 保持“成片创作完成”；`feedback.message` 独立展示。

当前验收状态：**L1 本地通过，L3 QA 待部署后复测。**

## 2. 安全与副作用

- 只访问固定 QA 域名，没有访问生产或其他环境。
- 只读取环境变量 `FIREFLY_MVA_QA_API_KEY`，没有输出或落盘密钥。
- 报告不记录完整素材 URL、签名参数、临时凭证或原始用户视频。
- 在确认“QA 尚未部署”之前，自动化脚本已创建两个 QA 首轮任务；收到确认后立即停止客户端 Poll，没有继续创建第二轮任务，也没有调用取消接口。停止本地 Poll 不等同于取消服务端任务。
- 后续只执行健康检查和已有会话 Poll 两个只读请求。

## 3. 本地代码改动

问题复现：

`completed` 被通用进度映射固定投影为“成片创作完成”，没有区分最终 `production_outcome`。同时：

- Terminal Callback 没有把结果类型传给进度描述；
- `queryResult` 在加载意图结果前生成了终态文案；
- Poll、queryResult、Webhook 三个出口因此可能不一致。

修复规则：

| 场景 | `current_node_description` |
| --- | --- |
| `completed + outcome=video` | `成片创作完成` |
| `completed + outcome=recommendation` | `已生成可执行方案` |
| 第二轮视频制作的模板匹配节点 | `正在匹配成片模板...` |
| 推荐用途的模板匹配节点 | `正在根据现有素材匹配可执行模板...` |

终态判断直接依赖稳定的 `production_outcome`，不依赖模板匹配内部用途字段。

涉及代码：

- `src/mp_video_agent/api/progress.py`
- `src/mp_video_agent/api/cloud_production_queries.py`
- `src/mp_video_agent/api/routes/cloud_production.py`
- `src/mp_video_agent/services/cloud_callback_delivery.py`

回归测试同步覆盖 Poll、queryResult 和 Webhook。

## 4. 本地自动化

执行命令：

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

结果：

```text
159 passed in 1.73s
```

先行红测：

```text
4 failed
```

四个失败分别精确命中：

- 公共进度描述；
- Cloud Poll 投影；
- Terminal Callback；
- queryResult。

修复后相同四项：

```text
4 passed in 0.83s
```

## 5. QA 只读基线

### 5.1 健康检查

| 项 | 值 |
| --- | --- |
| 时间 | `2026-08-24T17:07:10+08:00` |
| Method / Endpoint | `GET /api/rest/mva/health` |
| X-Request-ID | `qa-health-baseline-bf14bcdc9a6746bdaed4b6abd35ed02e` |
| HTTP | `200` |
| 服务状态 | `healthy` |
| 服务版本 | `v2` |
| Apollo | enabled，刷新无错误 |
| Kafka 日志 | producer connected，无失败或丢弃 |

该请求只读，不创建任务。

### 5.2 已有会话 Poll

| 项 | 值 |
| --- | --- |
| 时间 | `2026-08-24T17:07:10+08:00` |
| Method / Endpoint | `POST /api/rest/mva/out/cloud/poll` |
| X-Request-ID | `qa-poll-known-baseline-cfa8b1bee9964c7fb3dbfb7e622bed39` |
| conversation_id | `22ba82de86b84f9ab89fc496c2eac0ba` |
| HTTP / body code | `200 / 200` |
| status / current_node | `completed / completed` |
| current_node_description | `成片创作完成` |
| video_url | 空 |
| outcome / readiness | 未返回 |
| 推荐列表 | 未返回 |

事实判断：QA 当前部署不是本次工作区版本。该响应不能用于验证新的推荐完成文案，也不能证明本地修复失败。

## 6. 部署确认前的旧版本观察

真实脚本在 `2026-08-24 17:00～17:03 Asia/Shanghai` 启动。收到“QA 还没部署”后已中止。

旧版本观察：

- 首轮河马请求被快速受理；
- 运行轨迹仍出现 `render_template_features = 成片构想中...`；
- 首轮直接进入渲染并显示“成片创作完成”，没有按本次规则停在推荐态；
- 后续新协议分支没有形成可用于验收的完整证据；
- 第二个首轮任务在客户端停止时仍在执行素材理解。

这些记录只作为“QA 未部署”的辅助基线，不计入新版本用例通过率。

## 7. 用例矩阵

| 用例 | 本地自动化 | QA 新版本 | 当前结论 |
| --- | --- | --- | --- |
| MT-HIPPO-01 首轮返回推荐态 | 通过 | 未部署 | BLOCKED |
| MT-HIPPO-02A 第二轮选择第一个并成片 | 通过 | 未部署 | BLOCKED |
| MT-HIPPO-02B 仍要求河马并 Best-effort 成片 | 通过 | 未部署 | BLOCKED |
| MT-HIPPO-02C 普通偏好重新推荐 | 通过 | 未部署 | BLOCKED |
| B01 运行中拒绝并发续写 | 通过 | 未部署 | BLOCKED |
| B02 幂等键复用但文字变化 | 通过 | 未部署 | BLOCKED |
| B03 后续轮带素材 | 通过 | 旧版基线响应符合拒绝方向，不能代替新版本验收 | BLOCKED |
| B04 后续轮空意图 | 通过 | 旧版基线响应符合拒绝方向，不能代替新版本验收 | BLOCKED |
| B05 不存在会话 | 通过 | 未形成新版本证据 | BLOCKED |
| B06 第二轮后拒绝第三轮 | 通过 | 未部署 | BLOCKED |
| B07 Poll 固定公开 ID 返回最新 Turn | 通过 | 未部署 | BLOCKED |
| B08 推荐完成文案 | 通过 | QA 仍为旧文案 | BLOCKED |
| B09 视频完成文案与 feedback 分开展示 | 通过 | 未部署 | BLOCKED |

## 8. 部署后复测顺序

1. 同时部署 QA API 与 Worker，确认镜像包含本次提交。
2. 先执行健康检查，再用全新 `qa-` 标识创建会话。
3. 分别使用三个独立首轮会话执行 MT-HIPPO-02A、02B、02C。
4. 在首轮运行中执行 B01。
5. 首轮推荐完成后、第二轮创建前执行 B03、B04。
6. 第二轮受理后执行 B02，并 Poll 固定 `conversation_id` 验证 B07。
7. 第二轮终态后执行 B06。
8. 验证推荐终态为“已生成可执行方案”，视频终态为“成片创作完成”，feedback 始终单独展示。
9. 只读核验 Turn 关系：同一 `cloud_conversation_id`、索引 1/2、第二 Turn 正确指向第一 Turn。

## 9. 最终验收标准

以下条件全部满足后，QA 才能判定通过：

- 首轮河马需求返回 `recommendation + UNSUPPORTED + NEED_USER_INPUT`；
- 推荐终态不再显示“成片创作完成”；
- 第二轮选择模板或仍明确生成式要求都能生成视频；
- 第二轮模板匹配运行文案为“正在匹配成片模板...”；
- 公开 `conversation_id` 两轮固定；
- 第二轮完成后第三次 `/make` 返回 `409106`；
- Poll、queryResult、Webhook 对结果类型使用同一完成文案；
- 报告中不出现凭据或完整素材 URL。
