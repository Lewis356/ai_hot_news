# AI 资讯速递 (AI Hot News)

> 一个抓取国内外 AI 媒体 RSS,用 LLM 评估重要性,生成精美飞书卡片日报的小工具。

[![Python](https://img.shields.io/badge/python-3.9%2B-blue)]()
[![License](https://img.shields.io/badge/license-MIT-green)]()

## ✨ 特性

- 📰 **多源聚合** — 并行抓取 RSS 源(36 氪、量子位、TechCrunch AI 等)。
- 🤖 **多模型评估** — DeepSeek / OpenAI / Ollama / Rule-based 四档可切换。
- 🎯 **智能过滤** — 标题去重 + 24h 时间窗,只保留值得看的。
- 🎨 **飞书卡片** — 排名徽章(🥇🥈🥉)、五档重要性 emoji、配色随头条变化。
- 🔐 **HMAC 签名** — 飞书 Webhook 支持签名校验,防止伪造。
- 🛡️ **输出沙箱** — LLM 返回值自动 clamp / 转义,杜绝 Markdown 注入。
- 📊 **可观测** — 每阶段耗时、每源成功率、单行 METRICS 汇总。
- 🧪 **测试完备** — `pytest -q` 全绿;新增 HMAC、转义、sanitize、卡片美化测试。

## 🚀 5 分钟快速开始

### 1. 准备环境

```bash
git clone <repo>
cd ai_hot_news
python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

### 2. 填写密钥

```bash
cp .env.example .env
# 编辑 .env,至少填一个 AI Provider key 和 FEISHU_WEBHOOK_URL
```

> ⚠️ **安全提醒** — `.env` 包含真实密钥,**绝不提交**。如果曾被泄露,立刻轮换 DeepSeek / Feishu 凭证。

### 3. 干跑一次

```bash
python run_once.py
```

### 4. 启动每日定时任务

#### 方式 A — 本地长跑(简单,但依赖你的电脑开机)

```bash
python main.py
```

默认在 `config.yaml` 中配置的 `cron_hour:cron_minute` 时刻运行(默认 00:00)。

#### 方式 B — GitHub Actions 零运维(推荐)

项目自带 [`.github/workflows/daily-digest.yml`](.github/workflows/daily-digest.yml),每天 UTC 16:00(=北京时间 00:00)自动跑。详细步骤见 **[DEPLOY.md](DEPLOY.md)**——只需 3 步:push 代码、配 3 个 Secret、点一次 "Run workflow" 验证。

| 维度 | 本地 main.py | GitHub Actions |
|---|---|---|
| 机器关机 | 漏推 | 不影响 |
| 网络抖动 | 自己处理 | 平台自动重试 |
| 时区 | 本地时区 | 固定 UTC |
| 日志 | 本地 `logs/` | 失败时下载 artifact |
| 部署成本 | 0 | push + 配 3 个 secret |

## 🔌 AI Provider 对比

| Provider | 适用场景 | 费用 | 配置项 |
|---|---|---|---|
| `deepseek` (默认) | 中文友好,价格低 | 低 | `DEEPSEEK_API_KEY` + `ai.deepseek_model` |
| `openai` | 英文 / 高质量 | 中 | `OPENAI_API_KEY` + `ai.openai_model` |
| `ollama` | 完全离线 / 隐私 | 免费 | `OLLAMA_BASE_URL` + `ai.ollama_model` |
| `rule` | 无 LLM,纯启发式 | 免费 | (无) |

切换 Provider 只需修改 `config.yaml`:

```yaml
ai:
  provider: "openai"   # ← 改这里
  openai_model: "gpt-4o-mini"
```

## 📐 架构总览

```
config.yaml + .env
       │
       ▼
   load_config() ──► Config dataclass
                       │
   ┌───────────────────┼───────────────────────┐
   ▼                   ▼                       ▼
 RSS Fetcher       Dedup + Filter        AI Evaluator (4 providers)
   │                   │                       │
   └─────────► scheduler.run_daily_digest() ◄──┘
                       │
                       ▼
                Card Builder (美化的飞书卡片)
                       │
                       ▼
            Feishu send_card (HMAC 签名 + 重试)
                       │
                       ▼
                  飞书群机器人
```

## ⚙️ 可调参数一览 (`config.yaml`)

| 字段 | 默认值 | 说明 |
|---|---|---|
| `rss_sources` | 3 个 | RSS 源 `{name, url}` 列表 |
| `schedule.cron_hour` / `cron_minute` | `0` / `0` | 每日触发时间(24h) |
| `ai.provider` | `deepseek` | Provider 选择 |
| `ai.top_n` | `10` | 卡片入选数量 |
| `ai.max_candidates` | `60` | 喂给 LLM 的最大候选数 |
| `ai.max_retries` | `3` | LLM 调用重试次数 |
| `dedup.title_similarity_threshold` | `0.80` | 标题相似度阈值(0-1) |
| `logging.retention_days` | `30` | 日志保留天数 |

## 🧪 测试

```bash
pytest -q
```

测试覆盖:Models / Fetcher / Processor / JSON parser / Evaluator (4 个 provider) / Publisher (HMAC + 美化) / Scheduler。

## ❓ FAQ

**Q: 飞书 webhook 怎么开"签名校验"?**
A: 飞书群 → 群机器人 → 添加机器人 → 选"自定义机器人" → "安全设置" 勾选"签名校验",复制 secret 粘贴到 `.env` 的 `FEISHU_WEBHOOK_SECRET`。

**Q: Pipeline 全程失败,如何排查?**
A: 看 `logs/daily_YYYY-MM-DD.log`,最末一行 `METRICS {...}` 给出每阶段耗时与数量。

**Q: 怎么换 RSS 源?**
A: 编辑 `config.yaml` 的 `rss_sources`,保持 `{name, url}` 格式即可。

## 📁 项目结构

```
ai_hot_news/
├── main.py                     # 定时入口
├── run_once.py                 # 单次执行入口(调试)
├── config.yaml                 # 业务配置
├── .env(.example)              # 密钥
├── requirements.txt            # 运行时依赖
├── requirements-dev.txt        # 开发依赖
├── pyproject.toml              # PEP 621 元数据
├── src/
│   ├── config.py               # Config dataclass + 加载器
│   ├── logger.py               # loguru 配置
│   ├── models.py               # NewsItem / EvaluatedItem
│   ├── scheduler.py            # 拆分后的 pipeline 编排
│   ├── observability/          # StepTimer + Metrics
│   ├── fetcher/rss_fetcher.py  # 并发抓取 + per-source 报告
│   ├── processor/{dedup,filter}.py
│   ├── evaluator/              # base + 4 个 provider + _prompting
│   ├── publisher/              # card_builder(美化) + feishu(HMAC)
│   └── utils/redact.py         # 日志脱敏
└── tests/                      # pytest 全套
```

## 📜 License

MIT