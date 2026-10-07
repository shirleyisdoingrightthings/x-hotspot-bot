# X 热点 Bot

每天把 X（Twitter）上 AI 圈在吵什么整理成一份中文播报推到飞书，每条话题都带讨论度
最高的原帖直链。

它是飞书「AI 日报」机器人的第二块（深度层），稿子推到和 AI 产业日报同一个 webhook：

| 块 | 播什么 | 覆盖方式 |
|---|---|---|
| AI 产业日报 | 今天 AI 圈发生了哪些事 | 广度层，一天十来条 |
| X 热点（本 bot） | 当天最大那件事在 X 上被怎么吵的 | 深度层，一天一到两个话题 |
| AI Builder 日报 | 那二十几位 builder 本人说了什么 | 人物层，原推原话 |

别指望它给出「今天的热点清单」。AINews 的 Twitter Recap 是每天只挑一件最大的事往深里
扒的体例（2026-09-03 核对最近 6 期，9/1 那期 13 个小节全是 Fable 5.1 的不同侧面），
不是当天话题的巡览。覆盖一到两个话题是正常的，不是抓取出了问题——「今天有哪些事」
由 AI 产业日报负责。

## 为什么不用 X 官方 API

官方 API 没有免费档，$5/1K 帖且只给 7 天检索，全量检索要 Enterprise $42K/月起。
2026-08-31 逐一实测了能拿到「原帖链接 + 讨论度」的免费路子：

| 源 | 状态 | 带原帖直链 |
|---|---|---|
| AINews（news.smol.ai/rss.xml） | 主力 | 是，44–79 条/期 |
| Techmeme（techmeme.com/feed.xml） | 交叉验证 | 否 |
| neodrop.ai | 无 RSS（/rss.xml 404、/feed 返回 HTML） | — |
| digg.com/rss | 404 | — |
| buzzing.cc | 没有 X 子站（twitter./x. 子域 SSL 失败） | — |
| Nitter | 2026 年公共实例基本全灭 | — |
| RSSHub / RSS-Bridge twitter 路由 | 能跑但不适合生产 | — |

AINews 是压倒性最优解：swyx 团队每天扫 544 个 X 账号 + 12 个 subreddit，单期正文约
90KB，章节固定，每条论断后面都挂着原始 x.com 帖子链接。免费，有全量 RSS。

想要真实互动量排序，得接第三方 X API，见文末。

## 讨论度是怎么算的（别写错口径）

我们没有真实的点赞/转发数。排序依据是一条原帖在当天复盘里被引用了几次——既出现在
`What happened` 又出现在 `Critical` 的帖子，说明它在这件事的讨论里更居中。

这是讨论中心度的代理指标，不是互动量。`prompt.md` 把它列为硬性要求：稿子里不许写成
"最高赞"。注意 AI Builder bot 的口径正好相反（那边是 X 上的真实计数，可以直说），
两边别互相抄。

## 与另外几个 bot 的差别（改动时别抹平）

1. 时效窗口 48 小时，不是 24。X 上的讨论常要发酵一两天才到顶，24h 会把「昨天发、
   今天才吵起来」的话题整个漏掉。改窗口用 `X_BOT_WINDOW_H`，别改代码默认值。
2. 去重键是 x.com 原帖 URL，不是文章 URL。同一话题连着两天上榜没关系（讨论在演进），
   但同一条原帖不该被反复当新料播。`send` 只把 x.com 链接写进 `logs/sent_urls.json`。
3. send 有一道硬闸门：稿件里一条 x.com 原帖链接都没有就拒发并记 `[FAIL]`。
   这是这个 bot 存在的理由，别为了"至少发出去"而放宽。
4. AINews 可能停更或延迟。`fetch` 在窗口内取不到新一期时会退回最新一期，并在 context
   顶部打出 `⚠️ …距今 N 天`，要求写稿方向读者交代素材日期。

## 用法

```bash
bash claude_report.sh fetch     # 取材，输出给 Claude 写稿
bash claude_report.sh send      # 读 logs/report_draft.txt 推送
```

调试时用 `FORCE_RUN=1` 绕过当天幂等检查。

## 目录

| 文件 | 作用 |
|---|---|
| `x_report.py` | 主脚本，`--mode fetch` 取材 / `--mode send` 推送 |
| `sources.py` | 数据源层，provider 可插拔，换源只动这里 |
| `prompt.md` | 写稿规范，Claude routine 读取 |
| `health_check.sh` | 体检薄封装，逻辑在 `../shared/health_check_base.sh` |
| `auto_repair.sh` / `claude_catchup.sh` | 薄封装，逻辑在 `../shared/` |
| `com.shirley.x-hotspot-bot.plist.example` | 环境变量模板（实际 plist 含密钥，不进版本） |

## 部署

把 `.plist.example` 复制到 `~/Library/LaunchAgents/com.shirley.x-hotspot-bot.plist`，
填入 webhook 与代理端口。注意 `FEISHU_WEBHOOK` 要填 AI 产业日报那个群机器人的地址
（AI 三块共用一个，群里显示为同一个机器人）。主 plist 不承担调度，写稿由 `morning-catchup-daily-bots` 定时任务驱动。

换机与排障（launchd 日志路径、claude CLI 断链等）见 [TROUBLESHOOTING.md](https://github.com/shirleyisdoingrightthings/bot-ops/blob/main/TROUBLESHOOTING.md)。
