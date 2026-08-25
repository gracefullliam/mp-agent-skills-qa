# Cloud Video Production QA Skills

用于以正式产品用户视角调用 Firefly Cloud 智能成片 QA 环境的独立 Skill 仓库。

当前包含：

- [`cloud-video-production-qa-debugger`](./cloud-video-production-qa-debugger/SKILL.md)：检查 QA 网关和鉴权、统一通过 COS 直传本地图片/视频、创建或查询 QA 成片任务，并按用户自然语言继续同一个 Cloud 会话。

当前 QA Skill 版本为 `v1.5.0-qa.5`。它与正式用户交互保持一致，唯一固定差异是请求目标为 QA 环境；同时保留常见错误提示规则，并将模板推荐以 `title + previewUrl` 可点击列表展示。

多轮推荐规则：用户可以在同一 `conversation_id` 下用自然语言请求更多模板或推荐；每轮使用新的 `outer_request_id`，服务端通过推荐缓存排除已经展示过的候选。Debugger 只展示服务端返回的 `title` 和 `preview_url`，不自行选择、补足或伪造模板。

## 环境边界

Skill 固定使用：

```text
https://medi-qa.fireflyfusion.cn
```

QA 凭据只从以下环境变量读取：

```text
FIREFLY_MVA_QA_API_KEY
```

该变量必须保存具有 `produce` scope 的 QA Key。不得填入生产 Key，不得配置通用 API Key 回退，也不得把真实值提交到仓库、粘贴到提示词或打印到日志。

如需测试 Webhook，使用独立的 `FIREFLY_MVA_QA_WEBHOOK_SECRET`，不要复用生产回调密钥。

## 安装到 Codex

仓库为私有仓库，先确保本机 GitHub 身份有访问权限，然后执行：

```bash
npx --yes skills add \
  https://github.com/gracefullliam/mp-agent-skills-qa/tree/v1.5.0-qa.5 \
  --skill cloud-video-production-qa-debugger \
  --agent codex \
  --global \
  --yes
```

更新已安装版本：

```bash
npx --yes skills update cloud-video-production-qa-debugger --global --yes
```

如果返回 `No installed skills found matching`，说明当前副本没有被 `npx skills` 登记；重新执行上面的固定版本 `skills add`。`skills update` 只更新原安装源，不会自动从一个固定 tag 切换到另一个 QA 版本；升级或回滚时显式替换安装 URL 中的 tag。

安装或更新后，新建一个 Codex 任务以重新加载 Skill。

## 配置 QA Key

使用终端、CI/CD 或本机密钥管理器向 Codex 进程注入：

```bash
export FIREFLY_MVA_QA_API_KEY='<qa-produce-key>'
```

上面的值只在本机设置，不要把真实命令及其值提交到 Git、截图或工单。可复制 `.env.example` 作为字段清单，但 `.env` 文件已被 Git 忽略。

## 使用示例

诊断已有任务：

```text
使用 $cloud-video-production-qa-debugger 查询 QA 任务。
conversation_id: <qa-conversation-id>
需要检查持久化父任务投影时使用 queryResult；需要核验客户可见的当前轮状态和结果时使用 Poll。
```

使用本地素材做 QA 冒烟测试：

```text
使用 $cloud-video-production-qa-debugger 在 QA 环境做一次本地视频成片冒烟测试。
本地视频：/approved/workspace/clip.mp4
创作意图：生成一条节奏明快的短片
```

按正式产品方式逐轮交互，首轮完成后暂停：

```text
使用 $cloud-video-production-qa-debugger。
只执行首轮，Poll 到终态后停止，不要自动发送第二轮。
返回首轮结果和 conversation_id，等待我的下一条自然语言指令。
```

需要继续时，可在同一 `conversation_id` 下说“再给一些模板”“这些都不满意”等，验证服务端推荐缓存避重和后续模板确认。

所有本地图片和视频都统一调用 `/upload/init`，使用返回的单对象临时凭证交给腾讯云 COS SDK 上传，再调用 `/upload/complete` 获取 `/make` 所需 URL。Skill 不按文件大小分支；SDK 可在内部选择单 PUT 或分片。素材字节不经过 `https://medi-qa.fireflyfusion.cn` 网关，临时凭证不得打印或落盘。原 `/upload` 仅用于旧客户端兼容诊断。

Skill 内置 `scripts/make_from_local_media.py`，可直接处理图片、视频或混合素材：

```bash
uv run --script scripts/make_from_local_media.py \
  --input /approved/workspace/photo.jpg \
  --input /approved/workspace/clip.mp4 \
  --intent '生成一条节奏明快的短片' \
  --output-dir ./outputs \
  --wait
```

Skill 不会把 QA 请求切换到生产环境，也不会在 QA Key 失败时尝试生产 Key。
