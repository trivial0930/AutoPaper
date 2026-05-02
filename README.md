# VLA / CV / World Model Daily Paper Agents

这是一个自动追踪 VLA、CV、Robot Learning、World Model 和 World Action Model 论文更新的 Agent 工作流。它会从 arXiv 抓取论文，补充 Semantic Scholar 元数据，筛选相关论文，生成一句话中文总结，输出 Markdown 日报，并可推送到飞书群。

默认自动化方式是 GitHub Actions：每周三推送周一到周三的论文，每周日推送周四到周日的论文，生成 `daily_papers/YYYY-MM-DD.md`、更新 `latest_papers.json`，并把结果提交回仓库。

## 功能

- 每周三和周日从 arXiv 抓取 `cs.CV`、`cs.RO`、`cs.AI`、`cs.LG`
- 筛选 VLA、CV、Robot Learning、Multimodal、World Model、World Action Model 相关论文
- 使用 DeepSeek V4 生成简洁中文一句话总结
- 生成 Markdown 日报和完整 JSON
- 可选用 Semantic Scholar 补充 TLDR、引用数、PDF 链接
- 可选推送每日精选到飞书群
- 支持本地运行和 GitHub Actions 定时运行

## Agent 组成

| Agent | 作用 | 是否依赖 LLM |
| --- | --- | --- |
| `CollectorAgent` | 从 arXiv API 按日期和分类抓取论文 | 否 |
| `MetadataAgent` | 从 Semantic Scholar 补充 TLDR、引用数、PDF 链接 | 否 |
| `ClassifierAgent` | 判断论文是否属于 VLA、CV、World Model、World Action Model 等方向 | 可选 |
| `SummarizerAgent` | 为每篇论文生成一句话中文总结 | 可选 |
| `CuratorAgent` | 按相关性筛出每日值得看的论文 | 否 |
| `PublisherAgent` | 生成 Markdown 日报 | 否 |
| `NotifierAgent` | 推送日报到飞书 | 否 |
| `WorkflowAgent` | 串联完整流程 | 否 |

设计原则是：抓取、去重、存储、发布走确定性代码；相关性判断和总结交给 Agent/LLM。这样稳定，也容易调试。

## 快速部署

### 1. 复制仓库

推荐先 Fork 这个仓库，然后 clone 到本地：

```bash
git clone git@github.com:<你的用户名>/AutoPaper.git
cd AutoPaper
```

如果你不需要本地开发，也可以只 Fork，然后直接在 GitHub 上配置 Actions。

### 2. 配置 DeepSeek API Key

进入你的 GitHub 仓库：

```text
Settings -> Secrets and variables -> Actions -> Secrets -> New repository secret
```

新增：

```text
Name: DEEPSEEK_API_KEY
Value: 你的 DeepSeek API Key
```

API Key 属于敏感信息，必须放在 `Secrets`，不要提交到代码或 README。

### 3. 配置 DeepSeek V4 模型

进入：

```text
Settings -> Secrets and variables -> Actions -> Variables -> New repository variable
```

新增：

```text
Name: DEEPSEEK_MODEL
Value: deepseek-v4-flash
```

可选模型：

- `deepseek-v4-flash`：推荐默认值，速度快，适合每日论文快报
- `deepseek-v4-pro`：总结质量更强，但通常成本更高

如果不配置这个 variable，workflow 默认使用 `deepseek-v4-flash`。

### 4. 可选：配置 Semantic Scholar

Semantic Scholar 可以补充 TLDR、引用数和开放 PDF 链接。它不是必需项。

在 GitHub Secrets 添加：

```text
Name: SEMANTIC_SCHOLAR_API_KEY
Value: 你的 Semantic Scholar API Key
```

刚发布的 arXiv 论文可能还没有被 Semantic Scholar 收录，这种情况会被跳过，不会影响日报生成。

### 5. 可选：配置飞书推送

在目标飞书群里添加自定义机器人：

```text
飞书群 -> 群设置 -> 群机器人 -> 添加机器人 -> 自定义机器人
```

复制 Webhook URL，格式类似：

```text
https://open.feishu.cn/open-apis/bot/v2/hook/xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx
```

然后在 GitHub Secrets 添加：

```text
Name: FEISHU_WEBHOOK_URL
Value: 你的飞书机器人 Webhook URL
```

如果你开启了飞书机器人的“签名校验”，再添加：

```text
Name: FEISHU_SECRET
Value: 飞书机器人签名密钥
```

如果你开启了“关键词校验”，关键词请设置为：

```text
论文日报
```

推送正文会包含这个词。

### 6. 手动运行一次

进入：

```text
Actions -> Daily VLA/CV Papers -> Run workflow
```

保持默认参数即可。默认会使用半周窗口：

- 周一到周三运行时，抓取周一 00:00 到当前时间
- 周四到周日运行时，抓取周四 00:00 到当前时间

成功后你会看到：

- `daily_papers/YYYY-MM-DD.md`
- `latest_papers.json`
- 如果配置了飞书，群里会收到日报摘要

## GitHub Actions 参数

手动运行 workflow 时可以设置：

| 参数 | 默认值 | 说明 |
| --- | --- | --- |
| `days` | `2` | 当 `window=days` 时，抓最近 N 天 |
| `window` | `split_week` | `split_week` 为半周窗口；`last_sunday` 为最近周日到现在；`days` 为最近 N 天 |
| `no_llm` | `false` | 是否禁用 LLM 分类和总结 |
| `skip_semantic` | `false` | 是否跳过 Semantic Scholar |

定时任务默认北京时间每周三 09:00 和每周日 09:00 运行。配置位置在 `.github/workflows/daily-papers.yml`：

```yaml
schedule:
  - cron: "0 1 * * 3"
  - cron: "0 1 * * 0"
```

GitHub Actions 的 cron 使用 UTC 时间，`0 1 * * 3` 对应北京时间周三 09:00，`0 1 * * 0` 对应北京时间周日 09:00。

## 本地运行

当前实现只使用 Python 标准库，不需要安装第三方依赖。

首次试跑建议禁用 LLM 和 Semantic Scholar，确认 arXiv 抓取和本地日报生成正常：

```bash
python3 -m paper_agents run --config config.json --no-llm --skip-semantic
```

启用 DeepSeek：

```bash
export DEEPSEEK_API_KEY="你的 DeepSeek API Key"
export DEEPSEEK_MODEL="deepseek-v4-flash"
python3 -m paper_agents run --config config.json
```

生成内容：

- `daily_papers/YYYY-MM-DD.md`：每日论文日报
- `latest_papers.json`：完整论文 JSON
- `papers.db`：SQLite 论文库

## 常用命令

抓最近 2 天论文：

```bash
python3 -m paper_agents run --config config.json
```

指定日期运行：

```bash
python3 -m paper_agents run --config config.json --date 2026-05-01
```

抓最近 7 天：

```bash
python3 -m paper_agents run --config config.json --days 7
```

抓从最近一个周日 00:00 到现在的论文：

```bash
python3 -m paper_agents run --config config.json --since-last-sunday --timezone Asia/Shanghai
```

按半周窗口抓取论文，周一到周三从周一开始，周四到周日从周四开始：

```bash
python3 -m paper_agents run --config config.json --split-week-window --timezone Asia/Shanghai
```

同时导出完整 JSON：

```bash
python3 -m paper_agents run --config config.json --json-out latest_papers.json
```

用已有 JSON 重新生成总结，适合调试 prompt：

```bash
python3 -m paper_agents summarize-json --config config.json --json latest_papers.json --out latest_papers.resummarized.json --limit 20
```

测试飞书机器人连通性：

```bash
export FEISHU_WEBHOOK_URL="你的 Webhook URL"
export FEISHU_SECRET="如果开启签名校验才需要"
python3 -m paper_agents test-feishu
```

用已有 JSON 单独推送飞书：

```bash
python3 -m paper_agents notify-feishu --config config.json --json latest_papers.json
```

运行测试：

```bash
python3 -m unittest discover -s tests -p 'test_*.py'
```

## 配置说明

核心配置在 `config.json`：

```json
{
  "sources": {
    "arxiv_categories": ["cs.CV", "cs.RO", "cs.AI", "cs.LG"],
    "lookback_days": 2,
    "max_results_per_category": 50,
    "vla_keywords": ["vision-language-action", "embodied ai", "robot learning"],
    "cv_keywords": ["segmentation", "object detection", "vision-language"],
    "world_model_keywords": ["world model", "latent dynamics", "future prediction"],
    "world_action_model_keywords": ["world action model", "action-centric world model"]
  },
  "llm": {
    "enabled": true,
    "provider": "deepseek",
    "model": "deepseek-v4-flash"
  },
  "publisher": {
    "output_dir": "daily_papers",
    "top_k": 12,
    "include_irrelevant": false
  }
}
```

建议：

- 想多抓一点：提高 `max_results_per_category`
- 想更偏 VLA：扩充 `vla_keywords`
- 想更偏 World Model：扩充 `world_model_keywords`
- 想更偏 World Action Model：扩充 `world_action_model_keywords`
- 想看更多论文：提高 `publisher.top_k`
- 想调试分类：把 `include_irrelevant` 设为 `true`

如果想重新生成配置：

```bash
python3 -m paper_agents init-config
```

如果本地已有 `config.json`，命令会拒绝覆盖，需要先手动删除或改名。

## 切换到 OpenAI

把 `config.json` 里的 `llm.provider` 改成 `openai`：

```json
{
  "llm": {
    "enabled": true,
    "provider": "openai",
    "model": "gpt-4.1-mini"
  }
}
```

然后设置：

```bash
export OPENAI_API_KEY="你的 OpenAI API Key"
export OPENAI_MODEL="gpt-4.1-mini"
```

GitHub Actions 中对应添加：

```text
Secret: OPENAI_API_KEY
Variable: OPENAI_MODEL
```

## 飞书消息格式

飞书群会收到类似：

```text
论文日报 | VLA / CV / World Model / World Action Model | 2026-05-01
今日精选 12 篇

1. Paper Title
标签：VLA, Robot Learning | 分数：4.8/5
一句话总结：本文提出……
链接：https://arxiv.org/abs/xxxx.xxxxx
```

## 常见问题

### Actions 里显示 `FEISHU_WEBHOOK_URL is not configured`

说明 GitHub Secret 没配好，或者名字不对。必须是：

```text
FEISHU_WEBHOOK_URL
```

注意它是 Secret，不是 Variable。

### 飞书没有收到消息

先看 `Send Feishu notification` 这一步日志。

- 如果提示 Webhook 未配置，检查 `FEISHU_WEBHOOK_URL`
- 如果提示签名错误，检查 `FEISHU_SECRET`
- 如果机器人开启了关键词校验，关键词设置为 `论文日报`
- 如果 workflow 是旧提交的 rerun，不要点 `Re-run all jobs`，请从 workflow 页面重新点 `Run workflow`

### Semantic Scholar 返回 404

刚发布的 arXiv 论文可能还没有被 Semantic Scholar 收录。程序会跳过这一步并继续生成日报：

```text
Warning: Semantic Scholar enrichment skipped for xxxx.xxxxx: HTTP 404
```

这是正常现象。

### arXiv 抓到了 0 篇

可能是 arXiv 限流或日期窗口太短。建议手动运行时使用：

```bash
python3 -m paper_agents run --config config.json --since-last-sunday --timezone Asia/Shanghai --skip-semantic
```

日志会显示每个分类抓到了多少篇。

### 总结质量很差

先确认 GitHub Secrets 里有：

```text
DEEPSEEK_API_KEY
```

再确认 Variables 里模型名正确：

```text
DEEPSEEK_MODEL=deepseek-v4-flash
```

如果想要更强总结质量，可以改成：

```text
DEEPSEEK_MODEL=deepseek-v4-pro
```

### Push 失败：`non-fast-forward`

这是因为 Actions 自动提交日报后，远端 `main` 比本地更新。先 rebase：

```bash
git pull --rebase origin main
git push
```

## 本地定时运行

如果不想用 GitHub Actions，可以用 cron。

打开 crontab：

```bash
crontab -e
```

每周三和周日 9 点运行：

```cron
0 9 * * 3,0 cd "/path/to/AutoPaper" && DEEPSEEK_API_KEY="xxx" /usr/bin/python3 -m paper_agents run --config config.json --split-week-window --timezone Asia/Shanghai >> agent.log 2>&1
```

## 后续扩展建议

1. 增加 Notion、邮件、Slack、Telegram 推送。
2. 增加 embedding 排序，根据你收藏过的论文做个性化推荐。
3. 增加反馈机制，把“有用/无用”反馈写回偏好。
4. 接入 OpenReview，追踪 ICLR、NeurIPS、CoRL、CVPR 等会议投稿和接收状态。
5. 做一个 Web UI，展示每日论文、标签、搜索、收藏和阅读状态。
