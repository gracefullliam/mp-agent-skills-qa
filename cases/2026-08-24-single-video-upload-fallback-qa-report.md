# 0821 单视频上传兜底规则 QA 测试报告

## 1. 测试结论

测试日期：2026-08-24  
测试环境：本地代码 + QA `https://medi-qa.fireflyfusion.cn`  
需求：`0821-移动-单视频上传兜底规则&解决方案优化反馈`

结论：**单视频高光兜底规则专项通过；QA 单视频端到端冒烟通过。**

该规则的业务边界是：当 Cloud 请求只有一个素材、该素材是视频、源视频时长严格大于 6 秒，并且标准化后的最终结果只有一个有效高光时，将该高光按时间中点拆成两个首尾相接且不重叠的片段，为后续模板转场提供两个素材槽位。

## 2. 规则与边界

### 2.1 应触发

- `materials` 只有一个元素；
- 唯一素材类型为 `video`；
- 源视频时长 `> 6.0s`；
- 模型结果、客户端可信预处理结果或确定性模型失败兜底，最终都标准化为恰好一个有效高光；
- 拆分点为原高光的时间中点；
- 拆分后满足 `first.end_sec == second.start_sec`，且不存在重叠。

### 2.2 不应触发

- 视频时长缺失或无法探测；
- 视频时长 `<= 6.0s`；
- 混合素材（视频 + 图片）；
- 多个视频素材；
- 已有两个或更多有效高光；
- 高光结果为空或已有错误。

拆分只改变片段时间范围，保留原高光的 `event`、`score`、`provider` 等元数据，并追加 `single-video transition fallback` Warning。

## 3. 本地自动化测试

### 3.1 专项命令

```bash
env PYTHONDONTWRITEBYTECODE=1 \
.venv/bin/python -m pytest -p no:cacheprovider \
  tests/mp_video_agent/test_video_highlight.py \
  tests/mp_video_agent/test_foreign_cloud_edit.py -q
```

结果：

```text
58 passed in 0.61s
```

其中 `test_video_highlight.py` 共 40 项，覆盖：

- 单个长视频、单高光按中点拆分为两段；
- 拆分后首尾相接、不重叠；
- 原高光事件等字段保留；
- 源视频时长缺失或恰好 `6.0s` 时不拆分；
- 确定性高光兜底后，节点保持 `FALLBACK_SUCCESS` 并输出两个可渲染片段；
- 高光时间范围校验、模型重试和视频时长探测；
- 拆分后的片段继续进入渲染素材选择，保持 distinct clip ID 和 source range。

### 3.2 关键自动化结果

| 用例 | 预期 | 结果 |
| --- | --- | --- |
| 单视频 20s，唯一高光 `[5, 10]` | 拆为 `[5, 7.5]`、`[7.5, 10]` | 通过 |
| 单视频时长缺失 | 不拆分 | 通过 |
| 单视频恰好 6s | 不拆分 | 通过 |
| 模型失败后确定性兜底，单视频 20s | 节点不失败，输出两个片段 | 通过 |
| 拆分片段进入渲染输入 | 两个独立素材槽位，保留源时间段 | 通过 |

### 3.3 全量回归说明

全量测试当前不是干净基线，失败与本需求无直接关系：

- `pytest -x` 在 296 项通过后，因 `test_commercial_guard.py` 扫描工作区内 `.venv.python311-backup-20260814` 的第三方依赖而失败；
- 排除该 Guard 后为 `1017 passed, 34 failed, 3 skipped`，失败主要集中在运行时配置、迁移目标、向量库 URI、Suno 移除和共享环境状态等既有问题；
- 因此本报告只把 58 项单视频/渲染链路专项结果作为本需求验收依据，不把全量失败归因到单视频兜底规则。

## 4. QA 真实冒烟

### 4.1 健康检查

| 项目 | 结果 |
| --- | --- |
| Origin | `https://medi-qa.fireflyfusion.cn` |
| Health HTTP | `200` |
| 服务版本 | `v2` |
| Apollo | enabled，`last_error` 为空 |
| Kafka | producer connected，accepted/sent 数量一致，failed/dropped 为 0 |

### 4.2 单视频生产任务

测试使用此前已授权的 QA 单视频素材；报告不记录完整素材 URL、API Key 或临时凭证。

| 项目 | 结果 |
| --- | --- |
| `/api/rest/mva/out/cloud/make` | `200`，任务受理 |
| `conversation_id` | `fb5653d2-cf55-4301-9498-c8e9b3c02e9b` |
| Poll 轨迹 | `preprocess` → `tagging` → `render_template_matching` → `completed` |
| 终态 | `completed` |
| `video_url` | 非空 |
| `error_messages` | 空 |
| `queryResult` | `final_video_result.status=completed`，Provider 为 `foreign_cloud_edit` |
| 渲染素材适配 | `source_count=1`，`target_count=1`，模板要求素材数为 1 |

QA 任务证明单视频请求可以完整走完素材理解、模板匹配和渲染链路。当前客户可见的 Poll/queryResult 契约不返回 `highlight_segments_by_asset` 或 Warning，因此无法仅凭公共出参断言拆分后的两个时间段；精确拆分断言由本地 58 项自动化测试覆盖。

## 5. 安全与副作用

- 只访问固定 QA 域名，没有访问生产；
- API Key 仅从 `FIREFLY_MVA_QA_API_KEY` 环境变量读取，未输出或写入报告；
- QA 单视频任务会产生真实测试任务和一条成片结果，这是本次冒烟的预期副作用；
- 报告不记录完整素材 URL、签名 URL、COS 临时凭证、Webhook Secret 或用户视频内容。

## 6. 后续建议

1. 如果后续需要在 QA 做“规则本身”的黑盒验收，建议增加受控的调试出参或只读 step 详情，返回标准化后的高光段数量、时间范围和 Warning，但不要把内部模型原始响应暴露给客户。
2. 补充节点级负向用例：混合素材、多个视频、已有两段高光，确认这些输入不会误触发单视频规则。
3. 修复全量回归中的环境污染和配置隔离问题后，再将本专项加入稳定 CI 门禁。
