# AI 资讯速递 — 完整教程

> 本教程面向第一次接触项目的同学;**已熟悉 Python & 飞书机器人**的可直接看 [README.md](README.md) 的 5 分钟快速开始。

## 1. 环境准备

- **Python 3.9+**(本项目最低支持 3.9;推荐 3.11)
- 操作系统:Linux / macOS / Windows 均可
- 可访问外网(用于抓 RSS 与调用 LLM API)

```bash
python -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

## 2. 申请密钥

### 2.1 AI Provider(选其一)

| 用途 | 申请地址 |
|---|---|
| DeepSeek(默认推荐,中文便宜) | https://platform.deepseek.com/api_keys |
| OpenAI | https://platform.openai.com/api-keys |
| Ollama(本地) | 安装 [Ollama](https://ollama.com/download) 并 `ollama pull qwen2.5:7b` |

### 2.2 飞书机器人 Webhook

1. 打开目标飞书群 → 设置 → 群机器人 → 添加机器人 → **自定义机器人**
2. 名称随意;签名校验**建议开启**(见 §3.5)
3. 复制 Webhook URL(形如 `https://open.feishu.cn/open-apis/bot/v2/hook/xxxxxxxxxx`)
4. 如果开了签名校验,再复制 "签名校验密钥"

## 3. 配置项目

### 3.1 复制 `.env` 模板

```bash
cp .env.example .env
```

按需填入:

```env
DEEPSEEK_API_KEY=sk-你的真实key
FEISHU_WEBHOOK_URL=https://open.feishu.cn/open-apis/bot/v2/hook/你的uuid
FEISHU_WEBHOOK_SECRET=如果开了签名校验就填,否则留空
```

> ⚠️ **安全提醒**:`.env` 永远不要 commit。如果你曾把 `.env` 推过任何公开仓库,**立刻**在 DeepSeek / 飞书后台重置密钥。

### 3.2 编辑 `config.yaml`

```yaml
rss_sources:
  - name: "36氪"
    url: "https://36kr.com/feed"
  - name: "量子位"
    url: "https://www.qbitai.com/feed"
  - name: "TechCrunch AI"
    url: "https://techcrunch.com/category/artificial-intelligence/feed/"

schedule:
  cron_hour: 0          # 每天 00:00 触发(24h)
  cron_minute: 0

ai:
  provider: "deepseek"  # 可选:deepseek | openai | ollama | rule
  deepseek_model: "deepseek-chat"
  openai_model: "gpt-4o-mini"
  ollama_model: "qwen2.5:7b"
  max_candidates: 60    # 喂给 LLM 的最大候选数
  top_n: 10             # 卡片入选数量

dedup:
  title_similarity_threshold: 0.80  # 标题相似度阈值

logging:
  retention_days: 30    # 日志保留天数
```

### 3.3 安装依赖

```bash
pip install -r requirements.txt
# 想要跑测试/lint 再装:
pip install -r requirements-dev.txt
```

## 4. 干跑一次(必试)

```bash
python run_once.py
```

正常情况下你应该看到:

```
2026-06-29 14:00:00 | INFO     | Starting daily AI news digest pipeline
2026-06-29 14:00:00 | INFO     | Fetched 28 items from 36氪
2026-06-29 14:00:01 | INFO     | Fetched 22 items from 量子位
...
2026-06-29 14:00:05 | INFO     | METRICS {"fetched": 80, "deduped": 65, "recent": 18, "evaluated": 10, "duration_ms": {...}}
2026-06-29 14:00:05 | INFO     | Feishu card sent successfully
```

飞书群应同时收到一张精美卡片。

## 5. 启动每日定时服务

```bash
python main.py
```

进程会在 `cron_hour:cron_minute` 时刻自动触发;`Ctrl+C` 优雅退出。

## 6. 进阶

### 6.1 自定义 RSS 源

在 `config.yaml` 的 `rss_sources` 加条目即可,支持任何标准 RSS 2.0 / Atom 源:

```yaml
rss_sources:
  - name: "机器之心"
    url: "https://www.jiqizhixin.com/rss"
```

### 6.2 启用飞书 HMAC 签名(强烈推荐)

1. 飞书群 → 群机器人 → 你的自定义机器人 → 安全设置 → **勾选"签名校验"** → 复制密钥
2. `.env` 中:`FEISHU_WEBHOOK_SECRET=<复制的密钥>`
3. 重启服务。代码会自动用 HMAC-SHA256(`timestamp + secret`)对每个 POST body 签名。

> 启用后若 webhook 一直失败,通常是 `.env` 里的 secret 与飞书后台不一致。

### 6.3 切换 AI Provider

改 `config.yaml` 的 `ai.provider`,并填对应 key / model 即可。三种云端 provider 都用同一个共享 prompt(见 `src/evaluator/_prompting.py`),切换无副作用。

### 6.4 完全离线(规则评估)

`ai.provider: "rule"` — 不需要任何 API key,纯启发式打分,适合演示 / 调试 / API 配额耗尽时 fallback。

## 7. 持久化后台运行

### 7.1 Linux (systemd)

新建 `/etc/systemd/system/ai-hot-news.service`:

```ini
[Unit]
Description=AI Hot News Daily Digest
After=network-online.target

[Service]
User=www-data
WorkingDirectory=/opt/ai_hot_news
ExecStart=/opt/ai_hot_news/.venv/bin/python main.py
Restart=on-failure
RestartSec=30

[Install]
WantedBy=multi-user.target
```

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now ai-hot-news
sudo journalctl -u ai-hot-news -f
```

### 7.2 Docker

```dockerfile
FROM python:3.11-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
CMD ["python", "main.py"]
```

```bash
docker build -t ai-hot-news .
docker run -d --restart unless-stopped \
  --name ai-hot-news \
  --env-file .env \
  -v $(pwd)/logs:/app/logs \
  -v $(pwd)/config.yaml:/app/config.yaml:ro \
  ai-hot-news
```

## 8. 故障排查

| 现象 | 排查方向 |
|---|---|
| `Failed to send Feishu card after 3 attempts` | 看 `logs/daily_*.log`,通常 4xx=webhook URL/签名错,5xx=飞书侧问题 |
| `Provider 'xxx' failed: ...` | 主 provider 抛错,已自动 fallback 到 rule;若想要原始错误,看日志 |
| `No recent news after filtering` | RSS 源当天没更新,或 `cron_hour` 设置导致跨时区问题 |
| 卡片里全是 `\` 转义符 | 正常 — LLM 输出里有 Markdown 特殊字符,被 `_md_escape` 主动转义防注入 |
| 卡片 header 颜色不对 | 飞书后台需开启"卡片 JSON 2.0",见 README FAQ |

## 9. 开发相关

```bash
pytest -q                          # 跑全部测试
pytest --durations=10              # 看慢测试
pytest tests/test_publisher.py -v  # 只跑发布器相关
ruff check .                       # lint
mypy src/                          # 类型检查
```

主要目录:

```
src/
├── scheduler.py        ← pipeline 编排(已拆分为 _step_* 函数)
├── observability/      ← StepTimer + Metrics
├── fetcher/rss_fetcher.py
├── processor/{dedup,filter}.py
├── evaluator/          ← base + _prompting + 4 provider
├── publisher/          ← card_builder(美化) + feishu(HMAC)
└── utils/redact.py     ← 日志脱敏
```

## 10. 安全建议清单

- [ ] `.env` 永远不 commit(本仓库 `.gitignore` 已包含)
- [ ] 启用飞书 HMAC 签名(`FEISHU_WEBHOOK_SECRET`)
- [ ] 定期轮换 DeepSeek / OpenAI key
- [ ] 在 CI/服务器上以最小权限用户运行
- [ ] 监听日志,留意异常 `[REDACTED]` 出现频次(意味着某段代码正在尝试打印密钥)