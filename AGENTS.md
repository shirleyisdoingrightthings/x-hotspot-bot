# AGENTS.md — X 热点 Bot

给接手改这个 bot 的 Agent。先读 `README.md` 了解它是干什么的，这里只列**改动时最容易踩的坑**。

## 不变量（改之前先想清楚为什么要破）

1. **send 的原帖闸门不能放宽。** `run_send` 会检查稿件里有没有 `x.com/<user>/status/<id>`，
   一条都没有就 `[FAIL]` 拒发。这不是防御性编程，是这个 bot 的存在理由——
   一份只有转述、没有现场的 X 播报，价值等于零。曾经的需求原话是
   「以后这种 X 热度最好能给我回链到讨论度最高的原帖」。

2. **时效窗口是 48 小时，不是 24。** 另外几个 bot 基本是 24h（新闻的时效就是一天），
   但 X 上一条帖子的讨论常要发酵一两天才到顶。改成 24h 会漏掉约一半话题。
   要调用 `X_BOT_WINDOW_H` 环境变量，别改代码默认值。

3. **去重键只收 x.com 链接。** `record_sent_urls` 只写 `x_links`，不写全部 `hrefs`。
   同一个话题连着两天上榜是正常的（讨论在演进），拿 Techmeme 的媒体链接去重会误伤。

4. **「被引用次数」不是互动量。** `sources._rank_posts` 排序依据是一条原帖在当天
   AINews 复盘里被引用了几次，是**讨论中心度的代理指标**。`prompt.md` 明令禁止
   把它写成"最高赞"。要真实互动量只能接付费 API（`fetch_twitterapi` 占位里有步骤）。

5. **provider 失效要吵，不要静默降级。** 连续 3 天零产会打出 `=== SOURCE_ALERT ===`，
   写稿方须转述给用户。别加"某个源挂了就换另一个"的自动回退——静默换源会让
   数据质量悄悄下降而没人发现。

## 已知易踩的两个技术点

**AINews 的正文在 `content:encoded` 里，不在 `summary` 里。**
`summary` 只有一小段导语、**没有任何原帖链接**。`_entry_html` 特意只接受
长度 > 2000 的 content 值，就是为了防止退化成 summary 还以为抓成功了。

**抽上下文时必须替换整个 `<a>` 元素，不能只替换 URL 字符串。**
原帖链接绝大多数在 `href` 属性里、锚文本是别的字。只替 URL 的话，占位符会
连同 `<a ...>` 标签一起被 `TAG_RE` 吃掉，`context` 会全部变成空字符串——
而且不报错，只是稿子变得没有引语。这个坑 2026-08-31 踩过一次，
`_rank_posts` 里留了注释。改那段代码后**务必验证 `context` 非空率**：

```bash
/usr/bin/python3 -c "
import sys; sys.path.insert(0,'.')
import sources
iss = sources.fetch_ainews()['issues'][0]
print('空 context:', sum(1 for p in iss['posts'] if not p['context']), '/', len(iss['posts']))"
```

## AINews 的结构是浮动的

**单话题日**（如 2026-08-26 全篇只讲 GLM-5.3-Flash）里，`h2` 是同一件事的各个侧面
（What happened / Facts vs opinions / Supportive / Critical）；**多话题日** `h2` 才是真话题。
所以 `sources.py` **故意不按标题切话题**——切了会在单话题日产出十几个标题叫
「Supportive」的假话题。现在的做法是给写稿方一份 h2 提纲 + recap 正文 + 原帖排行，
让它自己判断当天是几件事。改这里之前先想清楚两种日子都怎么处理。

## 自测

```bash
cd ~/Desktop/bots/x-hotspot-bot
/usr/bin/python3 -m py_compile x_report.py sources.py
FORCE_RUN=1 /usr/bin/python3 x_report.py --mode fetch          # 看 marker 与原帖数
printf '<b>x</b>无链接\n' > logs/report_draft.txt
FORCE_RUN=1 /usr/bin/python3 x_report.py --mode send           # 应 [FAIL] 拒发
rm -f logs/report_draft.txt logs/run.log logs/run.jsonl        # 清掉测试残留
```

跑完记得删 `logs/run.log` 里的测试记录，否则 `already_ran_today` 会以为今天已经播过。

## 共享层

推送、去重、自愈、代理自愈全在 `../shared/bot_utils.py`，改那里所有 bot 同时生效，
**改完要手动 commit + push**（私有仓 bot-ops，不自动 push）。
新增 launchd job 时，输出重定向不要写进 Desktop / Documents / Downloads，
详见 `../shared/README.md` 里那条 `exit 78 (EX_CONFIG)` 的教训。
