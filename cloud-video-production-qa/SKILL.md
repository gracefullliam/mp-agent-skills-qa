---
name: cloud-video-production-qa
description: Use the Firefly Cloud Video Production public API from a user perspective in the QA environment at https://medi-qa.fireflyfusion.cn. Use when creating a QA video task from explicitly selected local image/video files, polling its result, or continuing a conversation with a natural-language revision. Keep the interaction concise and user-facing; use the separate cloud-video-production-qa-debugger skill only when the user explicitly requests diagnostics or evidence.
---

# Cloud Video Production QA

这是面向用户的 QA 成片 Skill，不是调试器。默认只完成用户要求、等待结果并返回可继续操作的简洁结论。内部执行细节、命令、日志、数据库字段和诊断证据不进入用户回复。

## 默认交互规则

- 使用固定 QA 地址：`https://medi-qa.fireflyfusion.cn`。
- 只读取 `FIREFLY_MVA_QA_API_KEY`，不读取、打印或回显任何密钥。
- 用户明确提供本地素材时才上传；不得扫描目录、猜测素材或自动追加素材。
- 首轮只提交用户给出的素材和自然语言意图，等待当前 Turn 结束后停止，不自动发起第二轮。
- 首轮得到推荐或 `NEED_USER_INPUT` 时，只展示简洁结论、推荐模板的 `title` 和 `previewUrl`，然后等待用户下一条自然语言指令。
- 用户明确继续时，复用固定 `conversation_id`，为本轮生成新的 `outer_request_id`。不要要求用户提供 Turn ID、task ID 或其他内部字段。
- 后续轮次没有新素材时，不重新执行素材上传；用户明确提供新素材时，才为新素材执行上传。
- 不因为推荐结果自动选择模板，不自动发送第二轮，也不自动连续执行多轮；只有用户明确要求自动化多轮时才连续执行。
- 用户说“再给一些模板”“这些都不满意”“还有别的吗”等时，将原话作为新的自然语言 Turn 提交给 Cloud `/make`；这属于请求更多模板，不是上传新素材，也不允许本地自行拼接候选。
- 用户要求取消当前制作时，对固定 `conversation_id` 调用 `/out/cloud/cancel`；不要只停止本地 Poll，也不要自动取消已经终态的会话。
- `conversation_id` 只在 API 调用和内部上下文中保存。除非用户明确索要或外部调用方必须接收，否则不要在自然语言回复中展示它。

## 静默执行边界

默认不要向用户展示或解释以下内容：

- shell 命令、脚本路径、工具调用过程和本地文件路径；
- `X-Request-ID`、`outer_request_id`、Turn ID、数据库 ID、state 文件名；
- HTTP 状态码、业务 code、SQL、堆栈、节点耗时、轮询次数和重试过程；
- “我先查询”“我正在上传”“我将重新执行”等内部计划和中间判断。

如果执行失败，只返回脱敏后的原因和用户下一步，不输出原始堆栈。只有用户明确要求“调试”“排查”“测试报告”或“原始接口响应”时，才切换到独立的 `$cloud-video-production-qa-debugger` Skill。

## QA 请求边界

需要直接构造请求或解释服务端响应时，按需读取 `references/api-contract.md`。不要加载 Debugger 的排查 playbook；用户明确要求诊断时改用独立的 `$cloud-video-production-qa-debugger`。

执行请求前：

1. 确认请求目标是固定 QA 地址。
2. 确认 `FIREFLY_MVA_QA_API_KEY` 存在且不打印其值。
3. 为每次 HTTP 请求生成唯一的 `X-Request-ID`。
4. 首次 `/make` 前生成一个 QA 专用 `outer_request_id`；网络超时或响应不明确时复用它。

涉及本地媒体时，优先使用 `scripts/make_from_local_media.py`，并为每个显式选择的文件传递 `--input`。上传流程必须是 `/upload/init` → COS 上传 → `/upload/complete`，确认得到非空素材 URL 后才能调用 `/make`。

创建任务后：

- `/make` 成功后只记录固定 `conversation_id`，不把内部请求标识暴露给用户；
- 当前 Turn 处于 `queued` 或 `running` 时，只 Poll，不重复 `/make`；
- 终态为 `completed`、`failed` 或 `cancelled` 时停止等待；
- `--wait` 可用于内部等待完整结果，但不得把脚本过程原样转述给用户。

## 多轮规则

- 每一轮都是同一个 Cloud 会话下的新自然语言指令。
- 每轮使用新的 `outer_request_id`，但不创建新的公共 `conversation_id`。
- 用户说“换一个模板”“更轻快一点”等修改时，直接提交这句自然语言，不要求用户填写模板编码。
- 用户请求更多模板或推荐素材时，直接提交原话，不添加模板编码、候选列表或内部 action 字段；服务端负责判断为 `request_more_templates` 并从推荐缓存中排除已经展示过的模板。
- `request_more_templates` 可以在当前会话允许的范围内重复执行；每次只展示服务端返回的 3～5 条候选，不自行补足、排序、杜撰 URL 或把历史候选重新冒充新候选。
- 用户明确选择某个已展示模板时，提交原话继续同一会话；不要重新上传素材。用户只是要求更多模板时，不要进入制作。
- 用户一句话要求“分别/各自/每个模板做一个成片”时，原样提交这句自然语言；服务端会将它解释成一个 Command 和多个串行 Job。不要把它拆成多次 `/make`，不要创建新 `conversation_id`，不要自行按序号匹配模板。
- 用户选择模板、坚持原始生成式要求或成片完成后再次修改时，都必须继续原会话；不得为了“再做一版”、模板序号或模板标题重新调用首轮 `/make`。首轮调用会丢失用户已选素材和推荐上下文，可能退化成默认模板。
- 模板序号（如 `1`、`2`、`3`）和模板标题只原样转发给服务端；如果服务端提示模板未出现在当前推荐批次，直接提示用户从当前列表重新选择，不得自行匹配、补候选或新建会话。
- 用户在后续轮次仍坚持首轮不可执行的生成式要求时，继续原会话提交原话；服务端会基于现有素材按 Best-effort 制作并给出解释，不要因为本地轮次计数或旧的“两轮”印象提前阻断。
- 用户修改原始制作意图、要求生成素材中不存在的主体/动作/内容时，仍交给 Cloud 判断；若返回 `NEED_USER_INPUT` 或推荐态，只展示结果并等待用户，不得强行制作。
- 不在 Skill 内固定“最多两轮”；以服务端当前会话和动作类型的响应为准。模板选择、更多模板和继续制作可能有独立的续写额度。
- 如果服务端提示当前会话仍在处理，告知用户稍后查看结果，不重复提交。
- 如果服务端明确提示本次动作达到最大轮次，告知用户“当前会话已达到最大修改次数，请重新开始”，不要自动新建会话、重新上传或重跑；不要仅因为本地计数达到两轮就提前拦截。

## 用户可见结果

推荐态：

```markdown
已根据现有素材生成可执行方案，请告诉我想使用哪种方向，或继续描述想要的效果。

### 可选模板

1. **模板标题** — [点击查看模板效果](https://example.com/preview.mp4)
2. **另一个模板** — 暂无预览
```

模板列表只展示 `title` 和公开 `preview_url`，对外标签统一使用 `previewUrl`。不要展示 `template_code`、内部评分、数据库字段或整段原始 JSON。

用户要求更多模板时，继续使用同一会话提交原话；返回新批次后仍只展示标题和“点击查看模板效果”，并等待用户下一步，不自动选择或制作。

成片完成：只返回“成片创作完成”和视频下载/预览链接。

批量成片完成：按服务端返回的 `video_results` 顺序展示每个模板标题、状态和视频链接；不要展示 `command_id`、`job_id` 或 `turn_id`。部分失败时保留已完成视频，并简洁说明未完成项。

批量制作运行中只向用户展示整体进度，例如“正在制作 2/3 个成片”；不要把内部 Job 列表、租约或 Turn 状态逐项展开。`status=partial_failed` 仍是可展示结果：保留成功视频，并对失败模板给出简短说明。

无法完全执行但已完成 best-effort：使用面向用户的简短解释，例如：

> 当前素材中没有要求的主体或动作，已忽略不可执行部分，并基于现有素材完成成片。

## 错误处理

把服务端错误转换成用户能理解的下一步：

- 未授权或权限不足：提示 QA 鉴权配置问题；
- 会话不存在：提示当前会话不可用，请重新开始；
- 当前任务仍在处理：提示稍后查看，不重复提交；
- 当前制作已取消：停止等待；如果用户之后提出新指令，继续复用原会话，由服务端决定是否接受；
- 达到当前动作的最大轮次：提示重新开始，不自动重建；不要根据本地两轮计数提前拦截；
- 上传过期、素材不符合要求：提示重新选择或重新上传素材；
- QA 暂时异常：仅对幂等请求做有限重试，仍失败时提示稍后重试。

不要基于服务端 `message` 文本做分支，不要把原始异常、堆栈或内部状态发送给用户。

## 调试副本

需要查看原始响应、请求标识、脚本输出、耗时、重试、数据库或 Webhook 证据时，改用 `$cloud-video-production-qa-debugger`。默认 Skill 不执行调试器的证据报告流程。
