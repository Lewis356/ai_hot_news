# Deployment Guide — 部署到 GitHub Actions

把每日推送从"本地 main.py 长跑"切换到 **GitHub Actions 定时 cron**,零服务器、零运维。

## 概览

- **触发时间**:每天 UTC 16:00(=北京时间次日 00:00)
- **入口**:`run_once.py`(不挂 scheduler,跑完即结束)
- **环境**:ubuntu-latest + Python 3.11
- **超时**:10 分钟
- **失败兜底**:日志以 artifact 形式保留 7 天

## Step 1 — 推送代码到 GitHub

```bash
cd d:\text\ai_hot_news
git add .
git commit -m "feat: add daily-digest GitHub Actions workflow"
```

第一次推送,在 GitHub 上**先手动建一个空仓库**(推荐私有,免得 .env 模板泄露时被人研究),然后:

```bash
git remote add origin https://github.com/<your-username>/ai_hot_news.git
git push -u origin main
```

或用 `gh` CLI:

```bash
gh repo create ai_hot_news --private --source=. --remote=origin --push
```

> ⚠️ `.gitignore` 已经屏蔽了 `.env`、`.venv/`、`logs/`,但**请在 push 前再确认一次**:
> `git status --ignored` 看一下有没有误带的本地密钥。

## Step 2 — 配置 3 个 Repository Secret

进 GitHub 仓库 → **Settings** → **Secrets and variables** → **Actions** → **New repository secret**,逐个加:

| Name | Value | 必填 | 来源 |
|---|---|---|---|
| `DEEPSEEK_API_KEY` | `sk-...` | ✅ | [platform.deepseek.com/api_keys](https://platform.deepseek.com/api_keys) |
| `FEISHU_WEBHOOK_URL` | `https://open.feishu.cn/open-apis/bot/v2/hook/xxx` | ✅ | 飞书群 → 群机器人 → webhook 地址 |
| `FEISHU_WEBHOOK_SECRET` | 飞书"签名校验"开关里给的 secret | ⛔ 强烈推荐 | 飞书群机器人 → 安全设置 → 签名校验 |

如果 `config.yaml` 里 `ai.provider` 切到 `openai` / `ollama`,再加对应密钥,workflow 已声明:

- `OPENAI_API_KEY`
- `OLLAMA_BASE_URL`(默认 `http://localhost:11434`,云端无意义,可忽略)

## Step 3 — 手动跑一次验证

**千万别等 cron**——先手动触发:

1. 仓库页面 → **Actions** 标签
2. 左侧选 **Daily AI News Digest**
3. 右侧 **Run workflow** → 选 `main` → 绿色 **Run workflow** 按钮

跑完看:

- ✅ **绿勾** + 飞书群同时收到卡片 → 配置全通,等 cron 即可
- ❌ **红叉** → 点进 run → 失败 step 有红字,最常见两种:
  - `DEEPSEEK_API_KEY is not set` → secret 没配或名字拼错
  - `FEISHU 4xx/5xx` → webhook URL 失效,或飞书群机器人被删除

## Step 4 — 调时区 / 频率

工作流文件 [`.github/workflows/daily-digest.yml`](.github/workflows/daily-digest.yml#L8-L10) 的 cron:

```yaml
- cron: "0 16 * * *"   # 北京时间 00:00
```

时区换算:`UTC = 北京时间 - 8h`,所以北京时间 `H:M` → UTC cron 用 `H-8:M`(注意跨日):

| 北京时间 | UTC cron 表达式 |
|---|---|
| 每天 00:00 | `0 16 * * *` |
| 每天 08:00 | `0 0 * * *` |
| 每天 12:00 | `0 4 * * *` |
| 每天 22:00 | `30 14 * * *` |
| 周一 09:00 | `0 1 * * 1` |

⚠️ GitHub Actions cron **偶尔会延迟 5-30 分钟**(共享集群的代价),对每日早报可以忽略。

## 排错清单

| 现象 | 排查 |
|---|---|
| Workflow 没出现在 Actions 列表 | YAML 路径必须是 `.github/workflows/*.yml` |
| 跑了但飞书没卡 | workflow 跑成功 ≠ 飞书收成功,看 step 里的 `Verify required secrets` 是否报 `FEISHU_WEBHOOK_URL is not set` |
| 飞书 403 / 签名失败 | `FEISHU_WEBHOOK_SECRET` 和飞书后台"签名校验"里显示的不一致 |
| 评估超时 (10 min) | DeepSeek 偶发;在 [main.py](main.py) 留可重试,或把 `timeout-minutes` 调到 15 |
| 出现 `ModuleNotFoundError` | 检查 `working-directory: ai_hot_news` 是否生效(子目录场景容易漏) |
| RSS 抓取空 | 源站临时 403/限流;看 artifact 里的日志 `METRICS` 行 |

## 关闭 / 暂停

- **临时关**:Actions 页面 → 选 workflow → 右上 `...` → **Disable workflow**
- **永久删**:删掉 `.github/workflows/daily-digest.yml` 即可,代码不动

## 回到本地跑(对比)

如果你想临时退回 `main.py` 本地长跑:

```bash
.venv\Scripts\activate
python main.py
```

`main.py` 内部用 `apscheduler` 跑 `CronTrigger(hour=0, minute=0)`,等价于 GitHub Actions 的 cron,但**依赖你电脑当时是否开机**。
