# AI Hot News 开源项目调研

> 调研快照：2026-10-16。仅使用项目仓库、仓库源码与官方平台文档。下列 7 个仓库在调研日均有近期提交；活跃度可由各仓库的 GitHub API `pushed_at` 字段复核。

## 结论先行

最值得采用的不是某个大框架，而是几个小而明确的边界：抓取必须返回真实的逐源状态；pipeline 必须返回结构化终态并映射到进程退出码；模型只能提供“判断”，不能改写来源事实；发布端要区分失败、成功和结果未知。

当前项目有三个优先级最高的问题：

1. **飞书签名算法不符合官方文档。** 官方算法以 `timestamp + "\n" + secret` 作为 HMAC key，对空字节串计算 HMAC-SHA256；当前 `src/publisher/feishu.py` 却以 `secret` 为 key、签名字符串为 message。官方示例 `timestamp=1599360473, secret=demo` 应得到 `l1N0gAcBjdwBvGm1xMjOF0XSyaLRpR7tuO5dHfhAYc8=`，当前实现得到不同结果。来源：[飞书自定义机器人官方文档](https://open.feishu.cn/document/client-docs/bot-v3/add-custom-bot#%E6%96%B9%E5%BC%8F%E4%B8%89%E8%AE%BE%E7%BD%AE%E7%AD%BE%E5%90%8D%E6%A0%A1%E9%AA%8C)。
2. **抓取报告会把失败记为成功。** `fetch_single()` 吞掉 HTTP/解析异常并返回空列表，外层 `_run()` 因未收到异常而写入 `ok: true`。这会把“全部源故障”误判成“今日无新闻”。Miniflux 的做法是保留 ETag、Last-Modified、错误计数和错误消息，并按 HTTP 状态分类；本项目不需要它的数据库，但应该保留同样清晰的结果语义。来源：[Miniflux feed model](https://github.com/miniflux/v2/blob/c317f84bc3779bc5d936b75408b631589983c81a/internal/model/feed.go)、[response handler](https://github.com/miniflux/v2/blob/c317f84bc3779bc5d936b75408b631589983c81a/internal/reader/fetcher/response_handler.go)。
3. **Actions 可能“假绿”。** `run_daily_digest()` 返回 `None`，抓取、评估或发送失败也不会自然产生非零退出码。GitHub 明确以 `0` 判成功、非零值判失败，因此 pipeline 终态必须传到 `run_once.py`。来源：[GitHub Actions 退出码文档](https://docs.github.com/en/actions/how-tos/create-and-publish-actions/set-exit-codes)。

## 参考项目与可借鉴模式

| 项目 | 已验证的设计 | 适合本项目的部分 |
|---|---|---|
| [RSSHub](https://github.com/DIYgod/RSSHub) | 每个来源是带名称、语言、示例、维护者和发现规则的独立 route；健康端点明确禁用缓存，并用原子 claim 防止同一路由缓存击穿。[route 示例](https://github.com/DIYgod/RSSHub/blob/bcf789cddcac2f01cf05b19bbcb6ce985aa9c776/lib/routes/towardsdatascience/latest.ts)、[缓存中间件](https://github.com/DIYgod/RSSHub/blob/bcf789cddcac2f01cf05b19bbcb6ce985aa9c776/lib/middleware/cache.ts)、[healthz](https://github.com/DIYgod/RSSHub/blob/bcf789cddcac2f01cf05b19bbcb6ce985aa9c776/lib/routes/healthz.ts) | 给每个 RSS 源稳定 ID 和语言元数据；逐源测试；确定性合并。不要引入其服务、Redis 或 route 框架。 |
| [Miniflux](https://github.com/miniflux/v2) | 条件请求、`Retry-After`、限流和错误类型被分开处理；条目身份优先使用 GUID/ID，再回退到 URL 或内容哈希。[request builder](https://github.com/miniflux/v2/blob/c317f84bc3779bc5d936b75408b631589983c81a/internal/reader/fetcher/request_builder.go)、[RSS identity](https://github.com/miniflux/v2/blob/c317f84bc3779bc5d936b75408b631589983c81a/internal/reader/rss/adapter.go) | 采用稳定 `item_id`、逐源结果和失败类别。条件 GET 与连续失败计数只有在有可靠持久状态后再加。 |
| [feedparser](https://github.com/kurtmckee/feedparser) | 明确区分可解析但不规范的 feed（`bozo`）与无内容的解析失败；官方支持 ETag/Last-Modified 与 304。[bozo 文档](https://github.com/kurtmckee/feedparser/blob/a22c5521cbb109871f1a2318948581901bd47e26/docs/bozo.rst)、[HTTP 缓存文档](https://github.com/kurtmckee/feedparser/blob/a22c5521cbb109871f1a2318948581901bd47e26/docs/http-etag.rst) | `parse_warning` 可继续使用已有 entries，`parse_error` 必须计为失败；不要把两者都压成空数组。 |
| [Pydantic AI](https://github.com/pydantic/pydantic-ai) | 结构化输出经类型校验后封装在 `AgentRunResult` 中，输出 validator 可以拒绝结果并消耗一个有上限的重试预算；文档也警告多层重试会相乘。[structured output](https://github.com/pydantic/pydantic-ai/blob/a156d80b51488fe99492d9074b0a28ef06e595c8/docs/output.md)、[retry layers](https://github.com/pydantic/pydantic-ai/blob/a156d80b51488fe99492d9074b0a28ef06e595c8/docs/retries.md) | 用 Pydantic 模型验证 LLM JSON；最多一次“修正输出”重试；记录实际 provider、usage 和 fallback。无需引入 Agent loop。 |
| [LiteLLM](https://github.com/BerriAI/litellm) | 按异常类型决定是否重试；失败 provider 进入 cooldown；fallback 路径记录已尝试目标，避免环和重复尝试。[retry policy](https://github.com/BerriAI/litellm/blob/859529ccbc1f3c0bf9daace4a9c92a84e60f439f/litellm/router_utils/get_retry_from_policy.py)、[fallback tracking](https://github.com/BerriAI/litellm/blob/859529ccbc1f3c0bf9daace4a9c92a84e60f439f/litellm/router_utils/fallback_event_handlers.py) | 只重试 429、超时、连接失败和 5xx；鉴权/参数/校验错误立即失败；fallback 只走一次 DeepSeek → Rule。不要引入完整路由器。 |
| [Apprise](https://github.com/caronc/apprise) | 通知插件将 token 标为 private，统一 timeout、节流和布尔结果；Feishu/Lark 是独立适配器。[Feishu plugin](https://github.com/caronc/apprise/blob/d61316d4cd18b333d60d6fa046512ec93117e415/apprise/plugins/feishu.py)、[Lark plugin](https://github.com/caronc/apprise/blob/d61316d4cd18b333d60d6fa046512ec93117e415/apprise/plugins/lark.py) | 保留 publisher seam、密钥脱敏和明确响应检查。当前只有一个目标，不值得增加通用通知依赖；而且该 Feishu 插件没有覆盖本项目需要的签名校验。 |
| [飞书官方 Python SDK](https://github.com/larksuite/oapi-sdk-python) | 官方 SDK 将鉴权、请求签名、token 管理和 typed request/response 封装在客户端边界。[README](https://github.com/larksuite/oapi-sdk-python/blob/0d9749a4728446a0ffa2e8374b37b5e1ce1cfd9c/README.md) | 继续用自定义 webhook 时无需引入 SDK；若未来需要消息查询、撤回或应用机器人能力，再迁移到 SDK，不要把两种认证模式混在一起。 |

## 建议采用的最小设计

### 1. 可靠的 pipeline 结果

- `run_daily_digest()` 返回 `DigestResult`，至少包含 `status`、阶段计数、逐源状态、`provider_requested`、`provider_used`、`fallback_used`、`publish_outcome` 和错误摘要。
- 终态建议固定为 `sent`、`empty_sent`、`fetch_failed`、`evaluation_failed`、`publish_failed`；只有前两者退出 `0`。
- “全部来源失败”和“来源成功但 24 小时内无条目”必须是不同状态。部分来源失败可以继续，但标记 `degraded=true`。
- 结束时只输出一条结构化 `RUN_SUMMARY`：`run_id`、`digest_id`、终态、各阶段数量与耗时、失败来源、实际 provider、fallback 和发布结果；不记录正文、key、webhook 或 secret。

### 2. 抓取、身份与 feed health

- `fetch_single()` 返回 `SourceFetchResult`，而不是用空列表同时表示无内容和失败；状态至少区分 `ok`、`http_error`、`parse_warning`、`parse_error`。
- 条目稳定身份按 `feed_id + entry GUID/ID`，缺失时用规范化 URL，再缺失才用标题与摘要哈希。先用稳定 ID 精确去重，再做标题相似度去重。
- 不要沿用“缺失日期 = 当前时间”。Miniflux 作为阅读器可以这样保证条目可见，但在“最近 24 小时”日报里会让同一篇无日期旧文每天变成新文；本项目应将无日期项排除出日报并计数。
- 并发抓取完成后按配置中的来源顺序、每源发布时间排序，再轮询组成候选，避免 `as_completed()` 的网络完成顺序影响 Top N。
- ETag/Last-Modified 很有价值，但 GitHub hosted runner 是临时环境；没有可靠持久状态时不要用 Actions cache 假装 correctness store。先做好逐次健康报告，之后再决定是否加小型状态存储。

### 3. 不信任模型输出中的事实字段

- 发送给模型的每条候选带内部 `candidate_id`；模型只返回 `candidate_id`、中文标题、摘要、重要度和关键词。
- URL、来源、发布时间必须由宿主代码按 ID 回填。拒绝未知 ID、重复 ID、越界分数、空摘要和超量关键词，不能让 RSS 文本或模型改写事实字段。
- 结构校验失败最多让模型修正一次，之后走规则模型；传输重试、输出修正重试和 fallback 分别设预算，避免 Pydantic AI 文档所示的重试倍增。
- 卡片展示 `provider_used`，不能展示配置里“想用的 provider”。

### 4. 发布安全与幂等语义

- 按飞书官方算法修复签名，并以官方示例参数形成独立固定向量测试；`FEISHU_WEBHOOK_SECRET` 在生产必须存在。
- 仅对明确可重试的情况重试。POST 发生 read timeout 时，服务端可能已经收到了消息，此时结果应为 `unknown`，盲目重试可能产生重复卡片。
- 自定义机器人 webhook 的官方请求体没有幂等键，因此仅靠 webhook 无法保证 exactly-once；这是由接口能力推导出的限制。最小做法是在卡片和日志写入稳定 `digest_id`（北京时间日期），并将“发送结果未知”暴露为失败供人工核对。若未来必须自动去重，应先引入可靠的成功投递账本或迁移到可查询消息的应用机器人，而不是把 GitHub cache 当数据库。
- HTTP 200 之后仍要校验 JSON `code == 0`；4xx/签名错误不要重试，429/5xx 尊重 `Retry-After` 并做有上限退避。飞书还规定单机器人 100 次/分钟、5 次/秒和 20 KB 请求体上限。来源：[飞书官方文档](https://open.feishu.cn/document/client-docs/bot-v3/add-custom-bot)。

### 5. GitHub Actions 部署

- 将日程从 `0 16 * * *` 调整为例如 `7 16 * * *`（北京时间 00:07）。GitHub 官方说明整点是高负载时段，定时任务可能延迟，负载足够高时甚至可能被丢弃；飞书也建议避开整点和半点，降低 `11232` 限流风险。schedule 只在默认分支运行，公开仓库 60 天无活动会自动停用。来源：[GitHub schedule 文档](https://docs.github.com/en/actions/reference/workflows-and-actions/events-that-trigger-workflows#schedule)、[飞书官方文档](https://open.feishu.cn/document/client-docs/bot-v3/add-custom-bot)。
- 保留 workflow 级 `concurrency`，但不要把它当历史幂等：它只能防并发，不能阻止稍后手动重跑同一天的任务。
- `workflow_dispatch` 明确提供 `dry_run` / `live`，dry-run 不接触飞书。运行前按所选 provider 校验 secrets，运行后写入 `$GITHUB_STEP_SUMMARY`，失败时上传已脱敏日志。
- 继续维持 `permissions: contents: read` 和 job timeout；第三方 Actions 最终应固定到完整 commit SHA，并用 Dependabot 更新。来源：[GitHub Actions 安全加固](https://docs.github.com/en/actions/reference/security/secure-use#using-third-party-actions)。

## 明确不建议照搬的模式

- 不部署 RSSHub、Miniflux、LiteLLM 或 Apprise 服务；这个项目的规模只需要借鉴边界和状态语义。
- 不增加数据库、Redis、消息队列或通用 plugin system，除非后续明确要求跨日 exactly-once、订阅管理或多通知渠道。
- 不在每一层都做 3 次重试；这会放大延迟、成本和重复投递概率。
- 不把抓取失败包装成“今日暂无新闻”，不把 fallback 后的规则结果标成 DeepSeek，不让日志/卡片只展示 happy path。
- 不让 LLM 生成或覆写 URL、来源和时间，不将完整 RSS HTML 当可信指令。
- 不使用网络完成顺序决定候选排名，也不使用“当前时间”伪造缺失发布时间。

## 推荐实施顺序

1. **P0：正确性** — 修复飞书签名；引入 `DigestResult` 与非零失败退出码；让抓取报告如实反映异常。
2. **P1：内容可信** — candidate ID 回填事实字段；Pydantic 校验；稳定排序、来源轮询、无日期策略和真实 provider 标记。
3. **P2：部署可靠** — 00:07 调度、dry-run、CI、Step Summary、脱敏失败日志和固定 Action SHA。
4. **P3：按需增强** — 只有出现真实的重复投递或带宽问题后，才增加持久投递账本和 ETag 状态。

## 活跃度核验

调研日通过 GitHub 仓库 API 核验 `pushed_at`：

- [RSSHub API](https://api.github.com/repos/DIYgod/RSSHub)
- [Miniflux API](https://api.github.com/repos/miniflux/v2)
- [feedparser API](https://api.github.com/repos/kurtmckee/feedparser)
- [Pydantic AI API](https://api.github.com/repos/pydantic/pydantic-ai)
- [LiteLLM API](https://api.github.com/repos/BerriAI/litellm)
- [Apprise API](https://api.github.com/repos/caronc/apprise)
- [飞书 Python SDK API](https://api.github.com/repos/larksuite/oapi-sdk-python)
