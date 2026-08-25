# Cloud Video Production QA Skills

Firefly Cloud 智能成片 QA 环境 Skill。交互方式与正式产品一致，固定差异仅为服务地址和 QA 凭据。

当前版本：`v1.6.0-qa.3`。

## Skills

- [`cloud-video-production-qa`](./cloud-video-production-qa/SKILL.md)：默认用户模式。上传用户明确选择的素材、提交自然语言指令、等待结果并返回简洁的推荐或视频。
- [`cloud-video-production-qa-debugger`](./cloud-video-production-qa-debugger/SKILL.md)：调试副本。仅在用户明确要求排查、原始响应或测试证据时使用。

模板推荐以模板标题和“点击查看模板效果”链接展示。`preview_url`/`previewUrl` 仅是内部字段映射，不能作为用户可见标签。后续模板选择、重复生成式要求、批量制作和成片后的修改必须复用原 `conversation_id`，不得新建首轮任务；未在当前推荐批次中的模板引用必须直接报冲突，不得随机回退。

默认 Skill 不展示 HTTP、内部 ID、命令、日志、SQL 或节点调试信息，也不会自动发送下一轮。用户后续继续对话时，Skill 复用固定 `conversation_id`，并将用户原话提交给服务端判断。

支持的用户行为包括：

- 选择一个已展示模板；
- 请求更多模板；
- 调整意图后继续制作；
- 对已有成片提出换音乐要求；当前通过更换模板重新成片，不支持单独替换音轨，音乐和画面效果可能一起变化；
- 对已有成片提出素材顺序调整；当前按 Best-effort 重新成片，不保证精确顺序；
- 用一句自然语言要求多个模板分别成片；
- 查询或取消当前制作。

换音乐和素材顺序调整都必须继续复用原 `conversation_id` 并提交用户原话。
服务端返回视频后，Skill 会同时展示非空的 `feedback.message`，说明当前编辑能力边界并请用户确认效果；
不会虚假宣称已经完成单独换音乐或精确素材重排。后续能力随 Agent 和组织逻辑版本迭代。

批量模板请求只提交一次 `/make`。服务端在同一会话内串行执行多个成片，并通过 `/poll` 返回聚合进度和有序 `video_results`。Skill 不拆成多轮、不新建会话、不自行解析模板序号。

## 环境

固定 QA 地址：

```text
https://medi-qa.fireflyfusion.cn
```

凭据只从以下变量读取：

```text
FIREFLY_MVA_QA_API_KEY
```

该 Key 必须具有 `produce` scope。不要把真实值写入仓库、聊天、截图或报告，也不要使用生产 Key 兜底。

## 安装

安装默认用户 Skill：

```bash
npx --yes skills add \
  https://github.com/gracefullliam/mp-agent-skills-qa/tree/v1.6.0-qa.3 \
  --skill cloud-video-production-qa \
  --agent codex \
  --global \
  --yes
```

需要调试能力时，再安装副本：

```bash
npx --yes skills add \
  https://github.com/gracefullliam/mp-agent-skills-qa/tree/v1.6.0-qa.3 \
  --skill cloud-video-production-qa-debugger \
  --agent codex \
  --global \
  --yes
```

升级或回滚时显式替换 URL 中的 tag。安装后新建一个 Codex 任务，让 Skill 重新加载。

## 使用

正常使用：

```text
使用 $cloud-video-production-qa，根据我选择的素材和自然语言要求制作视频。
```

后续直接继续说话即可。Skill 会复用同一 Cloud 会话；不会要求用户提供 Turn、Job 或内部任务标识。

需要排查时：

```text
使用 $cloud-video-production-qa-debugger 排查这个 QA 会话，并给我脱敏后的接口证据。
```
