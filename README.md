# VLA & CV Daily Paper Agents

这是一个自动追踪 VLA 和 CV 论文更新的小型 Agent 工作流。它每天从 arXiv 抓取论文，补充 Semantic Scholar 元数据，判断相关性，生成一句话中文总结，并输出 Markdown 日报。

## Agent 组成

| Agent | 作用 | 是否依赖 LLM |
| --- | --- | --- |
| `CollectorAgent` | 从 arXiv API 按日期和分类抓取论文 | 否 |
| `MetadataAgent` | 从 Semantic Scholar 补充 TLDR、引用数、PDF 链接 | 否 |
| `ClassifierAgent` | 判断论文是否属于 VLA、CV、Robot Learning、Embodied AI 等 | 可选 |
| `SummarizerAgent` | 为每篇论文生成一句话中文总结 | 可选 |
| `CuratorAgent` | 按相关性筛出每日值得看的论文 | 否 |
| `PublisherAgent` | 生成 Markdown 日报 | 否 |
| `WorkflowAgent` | 串联完整流程 | 否 |

设计原则是：抓取、去重、存储、发布走确定性代码；相关性判断和总结交给 Agent/LLM。这样稳定，也容易调试。

## 快速开始

当前实现只使用 Python 标准库，不需要安装第三方依赖。

项目里已经包含一份可直接修改的 `config.json`。首次试跑建议加 `--no-llm --skip-semantic`，确认 arXiv 抓取和本地日报生成没问题：

```bash
python3 -m paper_agents run --config config.json --no-llm --skip-semantic
```

如果你想重新生成配置，可以先删除 `config.json`，再运行：

```bash
python3 -m paper_agents init-config
```

生成内容：

- `daily_papers/YYYY-MM-DD.md`：每日论文日报
- `papers.db`：SQLite 论文库

## 使用 DeepSeek 生成高质量总结

默认配置使用 DeepSeek。设置环境变量：

```bash
export DEEPSEEK_API_KEY="你的 API key"
export DEEPSEEK_MODEL="deepseek-v4-flash"
```

然后运行：

```bash
python3 -m paper_agents run --config config.json
```

如果没有设置 `DEEPSEEK_API_KEY`，系统会自动退回规则分类和 Semantic Scholar TLDR/标题摘要。

## 切换到 OpenAI

设置环境变量：

```bash
export OPENAI_API_KEY="你的 API key"
export OPENAI_MODEL="gpt-4.1-mini"
```

并把 `config.json` 里的 `llm.provider` 改成 `openai`：

```json
{
  "llm": {
    "enabled": true,
    "provider": "openai",
    "model": "gpt-4.1-mini"
  }
}
```

然后运行：

```bash
python3 -m paper_agents run --config config.json
```

## 使用 Semantic Scholar

Semantic Scholar API 可以补充 TLDR、引用数和开放 PDF 链接。无 key 也能用，但可能被限流；建议申请 key 后设置：

```bash
export SEMANTIC_SCHOLAR_API_KEY="你的 Semantic Scholar key"
```

如果只想跳过 Semantic Scholar：

```bash
python3 -m paper_agents run --config config.json --skip-semantic
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
    "cv_keywords": ["segmentation", "object detection", "vision-language"]
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
- 想看更多论文：提高 `publisher.top_k`
- 想调试分类：把 `include_irrelevant` 设为 `true`

## 常用命令

抓最近 2 天论文：

```bash
python3 -m paper_agents run --config config.json
```

指定日期运行：

```bash
python3 -m paper_agents run --config config.json --date 2026-04-29
```

抓最近 7 天：

```bash
python3 -m paper_agents run --config config.json --days 7
```

抓从最近一个周日 00:00 到现在的论文，适合临时测试：

```bash
python3 -m paper_agents run --config config.json --since-last-sunday --timezone Asia/Shanghai
```

同时导出完整 JSON：

```bash
python3 -m paper_agents run --config config.json --json-out papers.json
```

## 每天自动运行

### GitHub Actions

当前仓库已经包含 `.github/workflows/daily-papers.yml`。推送到 GitHub 后，它会在每天北京时间 09:00 自动运行，也可以在 GitHub 页面手动触发：

1. 打开仓库的 `Actions` 页面。
2. 选择 `Daily VLA/CV Papers`。
3. 点击 `Run workflow`。

自动运行会做这些事：

- 运行测试
- 默认抓取从最近一个周日 00:00 到当前时间的 arXiv 论文，方便测试；手动触发时可把 `since_last_sunday` 改成 `false`，改用 `days`
- 可选调用 OpenAI 和 Semantic Scholar
- 生成 `daily_papers/YYYY-MM-DD.md`
- 如果配置了飞书 Webhook，把论文一句话总结推送到飞书群
- 把日报和 `latest_papers.json` 自动提交回仓库

如果你想启用 DeepSeek 总结，需要在 GitHub 仓库设置里添加 secret：

- `DEEPSEEK_API_KEY`
- `SEMANTIC_SCHOLAR_API_KEY`，可选

路径：

```text
Settings -> Secrets and variables -> Actions -> New repository secret
```

如果想改模型，可以添加 repository variable：

```text
DEEPSEEK_MODEL=deepseek-v4-flash
```

如果你想让总结质量更强、能接受更高费用，可以把变量改成：

```text
DEEPSEEK_MODEL=deepseek-v4-pro
```

### 推送到飞书

推荐使用飞书群的“自定义机器人”：

1. 打开目标飞书群。
2. 进入 `群设置 -> 群机器人 -> 添加机器人 -> 自定义机器人`。
3. 创建机器人后复制 Webhook URL，格式类似：

```text
https://open.feishu.cn/open-apis/bot/v2/hook/xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx
```

4. 在 GitHub 仓库里添加 secret：

```text
Settings -> Secrets and variables -> Actions -> New repository secret
```

必填：

```text
FEISHU_WEBHOOK_URL=你的飞书机器人 Webhook URL
```

如果你在飞书机器人安全设置里开启了“签名校验”，再添加：

```text
FEISHU_SECRET=飞书机器人签名密钥
```

然后去 `Actions -> Daily VLA/CV Papers -> Run workflow` 手动跑一次。成功后，飞书群会收到类似：

```text
论文日报 | VLA / CV / World Model | 2026-04-30
今日精选 12 篇

1. Paper Title
标签：VLA, Robot Learning | 分数：4.8/5
一句话总结：本文提出……
链接：https://arxiv.org/abs/xxxx.xxxxx
```

本地测试飞书推送：

```bash
export FEISHU_WEBHOOK_URL="你的 Webhook URL"
export FEISHU_SECRET="可选，如果开启签名校验才需要"
python3 -m paper_agents run --config config.json --days 1 --notify-feishu
```

用已经生成的 `latest_papers.json` 单独推送飞书：

```bash
export FEISHU_WEBHOOK_URL="你的 Webhook URL"
export FEISHU_SECRET="可选，如果开启签名校验才需要"
python3 -m paper_agents notify-feishu --config config.json --json latest_papers.json
```

只测试飞书机器人连通性：

```bash
export FEISHU_WEBHOOK_URL="你的 Webhook URL"
export FEISHU_SECRET="可选，如果开启签名校验才需要"
python3 -m paper_agents test-feishu
```

如果 GitHub Actions 没有推送到飞书，先看 `Send Feishu notification` 这一步日志：

- `FEISHU_WEBHOOK_URL is not configured` 表示 GitHub Secret 名称没配对。
- `Feishu notification failed` 后面的错误通常是签名密钥、关键词校验或 Webhook 地址问题。

如果你的飞书机器人设置了“关键词校验”，请把关键词设为 `论文日报`，因为推送正文会包含这个词。

### macOS / Linux cron

打开 crontab：

```bash
crontab -e
```

加入一行，每天 9 点运行：

```cron
0 9 * * * cd "/Users/rongzechen/Documents/New project 5" && /usr/bin/python3 -m paper_agents run --config config.json >> agent.log 2>&1
```

如果你需要 API key，建议在命令前加上环境变量：

```cron
0 9 * * * cd "/Users/rongzechen/Documents/New project 5" && OPENAI_API_KEY="xxx" SEMANTIC_SCHOLAR_API_KEY="yyy" /usr/bin/python3 -m paper_agents run --config config.json >> agent.log 2>&1
```

### GitHub Actions

如果后续你把项目放到 GitHub，可以加一个定时 workflow，每天自动生成日报并提交。这个版本先保留本地运行方式，避免你还没确认推送渠道前就把流程复杂化。

## 后续扩展建议

1. 增加 `NotifierAgent`：把日报推到飞书、Slack、Telegram、邮件或 Notion。
2. 增加 `EmbeddingRankerAgent`：根据你收藏过的论文做相似度排序。
3. 增加 `FeedbackAgent`：你把论文标为“有用/无用”，它自动更新关键词和偏好。
4. 接入 OpenReview：追踪 ICLR、NeurIPS、CoRL、CVPR 等会议投稿和接收状态。
5. 做一个 Web UI：展示每日论文、标签、搜索、收藏和阅读状态。

## 验证

运行单元测试：

```bash
python3 -m unittest discover -s tests -p 'test_*.py'
```
