# Cloud Video Production QA Skills

用于调试 Firefly Cloud 智能成片 QA 环境的独立 Skill 仓库。

当前包含：

- [`cloud-video-production-qa-debugger`](./cloud-video-production-qa-debugger/SKILL.md)：检查 QA 网关和鉴权、小文件 multipart 上传、大视频 COS 直传、创建或查询 QA 成片任务，并诊断 Poll/queryResult/Webhook 和公共错误码。

当前 QA 候选版本为 `v1.2.0-qa.1`；它用于验证 COS 直传协议，不代表生产环境已经发布该能力。

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
  https://github.com/gracefullliam/mp-agent-skills-qa/tree/v1.2.0-qa.1 \
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
先使用 queryResult；只有需要刷新下游渲染状态时才 Poll。
```

使用本地素材做 QA 冒烟测试：

```text
使用 $cloud-video-production-qa-debugger 在 QA 环境做一次本地视频成片冒烟测试。
本地视频：/approved/workspace/clip.mp4
创作意图：生成一条节奏明快的短片
```

对于大视频，Skill 会先调用 `/upload/init`，使用返回的单对象临时凭证直接分片上传腾讯云 COS，再调用 `/upload/complete` 获取 `/make` 所需 URL。素材字节不经过 `https://medi-qa.fireflyfusion.cn` 网关；临时凭证不得打印或落盘。

Skill 不会把 QA 请求切换到生产环境，也不会在 QA Key 失败时尝试生产 Key。
