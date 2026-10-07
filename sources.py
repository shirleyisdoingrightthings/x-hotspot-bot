#!/usr/bin/python3
"""
X 热点 Bot 的数据源层（provider）。

为什么单独一个文件：X 官方 API 没有免费档，能拿到「原帖链接 + 讨论度」的路子
不止一条，而且都可能失效。把取材抽成 provider，换源时只动这里，x_report.py 不用改。

现有 provider（2026-08-31 实测可用，均直连 200）：
  ainews    主力。原站 news.smol.ai/rss.xml 自 2026-09-04 起 402（见 AINEWS_FEEDS
            处的说明），现以 latent.space/feed 兜底，取其中的 [AINews] 期刊。
            每日扫 544 个 X 账号 + 12 个 subreddit，
            单期正文约 90KB，**每条论断后面都挂原始 x.com 帖子链接**（实测 44~79 条/期）。
            章节结构固定：AI Twitter Recap → Top Story → Facts vs Opinions →
            Different perspectives（supportive / neutral / critical）→ AI Reddit Recap。
  techmeme  techmeme.com/feed.xml —— 交叉验证用。它不给 X 原帖，只用来确认
            「AINews 说的这件事，主流科技媒体是不是也在报」，避免把小圈层的口水
            当成行业热点。

已验证不可用、不要再试（2026-08-31）：
  - neodrop.ai   /rss.xml 404、/feed 返回 HTML，没有 RSS，只能爬页面
  - digg.com/rss 404
  - buzzing.cc   有 tech / hn / reddit / stocks 子站，但**没有 X 子站**
                 （twitter. 与 x. 子域 SSL 直接失败），补的是 HN/Reddit 不是 X
  - Nitter       2026 年公共实例基本全灭
  - RSSHub / RSS-Bridge 的 twitter 路由：能跑，但业界共识是别用于生产
"""

import html
import re
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "shared"))
# X_POST_RE 在 bot_utils 里定义（ai-builder-bot 的出稿闸门也用它）；
# 这里 re-export，本模块内与 x_report.py 的 sources.X_POST_RE 用法都不变。
from bot_utils import fetch_rss, parse_entry_date, is_ai_relevant, X_POST_RE

# X 话题的时效窗口比新闻长：一条帖子的讨论往往要发酵一两天才到顶，
# 24h 窗口会把「昨天发、今天才吵起来」的话题整个漏掉。
DEFAULT_WINDOW_H = 48

# 2026-09-04：news.smol.ai 整站返回 402 Payment Required，body 是 Vercel 的
# DEPLOYMENT_DISABLED（部署因账单被停用）——/rss.xml、/feed.xml、/rss、首页、
# smol.ai/news 全部同样 402，不是本机代理或限流的问题。AINews 本身没停，它已
# 并入 Latent Space，同一批 [AINews] 期刊在 latent.space 的 feed 里照常更新，
# 正文结构与原站一致（实测 3 期 45 条原帖，Different opinions 分歧段完整）。
# 所以做成「原站优先 + Latent Space 兜底」：原站续费恢复后自动切回去，不用再改。
# requires_tag=True 表示该 feed 混有非 AINews 的常规文章（播客、专栏），
# 必须按标题过滤，否则会把一篇播客文当成一期复盘收进来。
# 2026-09-04 晚：按用户决定，latent.space 转正为首选，不再每天先去撞一次原站的 402。
# 原站保留在末位——万一它续费恢复且 latent.space 那边出问题，还能兜一手；
# 正常情况下第一个 feed 就成功，循环直接 break，不会产生多余请求。
AINEWS_FEEDS = (
    ("https://www.latent.space/feed", True),
    ("https://news.smol.ai/rss.xml", False),
)
AINEWS_TAG = "[ainews]"
TECHMEME_FEED = "https://www.techmeme.com/feed.xml"

HEADING_RE = re.compile(r"(?is)<h([1-4])[^>]*>(.*?)</h\1>")
ANCHOR_RE = re.compile(r'(?is)<a\b[^>]*href=["\']([^"\']*)["\'][^>]*>(.*?)</a>')
TAG_RE = re.compile(r"(?s)<[^>]+>")
WS_RE = re.compile(r"[ \t]+")


def _plain(fragment: str, limit: int = 0) -> str:
    """HTML 片段 → 纯文本。保留换行结构，压掉多余空格。"""
    text = re.sub(r"(?i)<br\s*/?>", "\n", fragment)
    text = re.sub(r"(?i)</(p|li|div|h[1-6])>", "\n", text)
    text = TAG_RE.sub("", text)
    text = html.unescape(text)
    text = WS_RE.sub(" ", text)
    text = re.sub(r"\n{3,}", "\n\n", text).strip()
    return text[:limit] if limit else text


def _entry_html(entry) -> str:
    """取一条 RSS 条目的全文 HTML。AINews 的正文在 content:encoded 里，
    summary 只有一小段导语，拿错了就没有原帖链接。"""
    for item in (getattr(entry, "content", None) or []):
        value = item.get("value") if isinstance(item, dict) else getattr(item, "value", "")
        if value and len(value) > 2000:
            return value
    return getattr(entry, "summary", "") or ""


def _twitter_section(body: str) -> str:
    """截出 AI Twitter Recap 那一段。取不到就退回全文——宁可多给写稿方一些
    Reddit 素材，也不要因为站点改版就整轮零产。"""
    heads = list(HEADING_RE.finditer(body))
    start = end = None
    for h in heads:
        title = _plain(h.group(2)).lower()
        if start is None and "twitter recap" in title:
            start = h.start()
            continue
        if start is not None and ("reddit recap" in title or "discord recap" in title):
            end = h.start()
            break
    if start is None:
        return body
    return body[start:end] if end else body[start:]


def _outline(section: str) -> list:
    """Twitter Recap 段的 h2 提纲，让写稿方一眼看出这期覆盖了哪些面。

    刻意不按标题切块：AINews 的结构是浮动的——**单话题日**（如 2026-08-26 全篇
    只讲 GLM-5.3-Flash）里 h2 是同一件事的各个侧面（What happened / Facts vs
    opinions / Supportive / Critical），按 h2 切会把一件事拆成十几个假话题，
    标题还全是「Supportive」这种没有信息量的词。多话题日 h2 才是真话题。
    与其猜，不如把提纲和正文一起给写稿方，让它自己判断当天是几件事。
    """
    return [_plain(m.group(2)) for m in HEADING_RE.finditer(section)
            if m.group(1) == "2"]


def _condense(section: str, budget: int) -> str:
    """把 Twitter Recap 压到预算内，**但必须保住「分歧」那几段**。

    起因（2026-08-31 首次跑通全流程时发现）：单纯 text[:budget] 会从头截，
    而 AINews 把 Supportive / Neutral / Critical 放在很靠后的位置——6000 字的
    截断正好把分歧全砍掉，写稿方只看得到一片叫好。prompt.md 又要求每条话题
    都给出正反两面，等于要求它凭空编。

    所以改成两段式：开头（发生了什么）拿 55% 预算，从「Facts vs opinions」
    或「Different perspectives」起的那一段拿 45%，中间用省略号接上。
    """
    text = _plain(section)
    if len(text) <= budget:
        return text
    head_budget = int(budget * 0.55)
    tail_budget = budget - head_budget
    for anchor in ("Different perspectives", "Facts vs opinions"):
        idx = text.find(anchor)
        if idx > head_budget:
            return (text[:head_budget].rstrip()
                    + "\n\n…（中间的技术细节已略，完整版见上面的原文链接）…\n\n"
                    + text[idx:idx + tail_budget])
    return text[:budget]


def _rank_posts(section: str, max_posts: int, ctx_chars: int) -> list:
    """把段落里的原帖按「被引用次数」排序，并带上首次出现处的上下文。

    **被引用次数就是我们的讨论度代理指标**：一条帖子在同一天的复盘里被反复
    引用（既出现在 What happened，又出现在 Critical），说明它在这件事的讨论中
    更居中。这不是真实的点赞/转发数，**写稿时必须如实说明口径，不能写成"最高赞"。**
    """
    order, meta = [], {}
    for m in X_POST_RE.finditer(section):
        handle, pid = m.group(1), m.group(2)
        if pid not in meta:
            meta[pid] = {"handle": handle, "url": f"https://x.com/{handle}/status/{pid}",
                         "mentions": 0, "idx": len(order)}
            order.append(pid)
        meta[pid]["mentions"] += 1

    # 用占位符替掉链接再转纯文本，这样才能定位每条帖子周围说了什么。
    # ⚠️ 必须替换整个 <a> 元素、而不是元素内的 URL 字符串：原帖链接绝大多数
    # 出现在 href 属性里、锚文本是别的字（"1"、"this post"），只替 URL 的话
    # 占位符会连同 <a ...> 标签一起被 TAG_RE 吃掉，context 全空。
    def _mark_anchor(m):
        href, inner = m.group(1), m.group(2)
        hit = X_POST_RE.search(href)
        if not hit:
            return inner
        return f"{inner} ⟦P{meta[hit.group(2)]['idx']}⟧ "

    marked = ANCHOR_RE.sub(_mark_anchor, section)
    # 兜底：没包在 <a> 里的裸链接
    marked = X_POST_RE.sub(
        lambda m: f" ⟦P{meta[m.group(2)]['idx']}⟧ ", marked)
    text = _plain(marked)

    for pid in order:
        info = meta[pid]
        token = f"⟦P{info['idx']}⟧"
        pos = text.find(token)
        if pos < 0:
            info["context"] = ""
            continue
        left = max(0, pos - ctx_chars)
        snippet = (text[left:pos] + text[pos + len(token):pos + len(token) + 60])
        info["context"] = re.sub(r"⟦P\d+⟧", "", snippet).strip()

    ranked = sorted(meta.values(), key=lambda d: (-d["mentions"], d["idx"]))
    return [{k: v for k, v in d.items() if k != "idx"} for d in ranked[:max_posts]]


def fetch_ainews(window_h: int = DEFAULT_WINDOW_H, max_issues: int = 3,
                 max_posts: int = 18, recap_chars: int = 9000,
                 ctx_chars: int = 200) -> dict:
    """主力源。返回 {"name","issues","raw_count","note","stale_days"}。

    每期：{title, url, date, outline:[h2...], recap:纯文本, posts:[{handle,url,mentions,context}]}
    """
    # 按 AINEWS_FEEDS 顺序取第一个真正有货的 feed。带 tag 的 feed 要多取一些，
    # 因为过滤掉非 AINews 文章后剩下的期数会少一半左右。
    entries = []
    for feed_url, requires_tag in AINEWS_FEEDS:
        got = fetch_rss(feed_url, limit=max_issues * (6 if requires_tag else 3))
        if requires_tag:
            got = [e for e in got
                   if AINEWS_TAG in (getattr(e, "title", "") or "").lower()]
        if got:
            entries = got
            break
    if not entries:
        return {"name": "ainews", "issues": [], "raw_count": 0,
                "note": "RSS 抓取失败", "stale_days": None}

    now = datetime.now(timezone.utc)
    cutoff = now - timedelta(hours=window_h)
    picked = []
    for e in entries:
        dt = parse_entry_date(e)
        if dt and dt < cutoff:
            continue
        picked.append((dt, e))
        if len(picked) >= max_issues:
            break

    # 窗口内一期都没有（周末停更 / 站点延迟 / 停止更新）时，仍拿最新一期兜底，
    # 但把「最新一期距今几天」一并报出去，让写稿方能主动向读者交代素材新鲜度。
    stale_days = None
    if not picked and entries:
        dt = parse_entry_date(entries[0])
        picked = [(dt, entries[0])]
        if dt:
            stale_days = round((now - dt).total_seconds() / 86400, 1)

    issues, total_posts = [], 0
    for dt, e in picked:
        body = _entry_html(e)
        if not body:
            continue
        section = _twitter_section(body)
        posts = _rank_posts(section, max_posts, ctx_chars)
        if not posts:
            continue  # 没有原帖链接的一期对我们没用
        total_posts += len(posts)
        issues.append({
            "title": getattr(e, "title", "") or "AINews",
            "url": getattr(e, "link", "") or "",
            "date": dt.strftime("%Y-%m-%d") if dt else "",
            "outline": _outline(section),
            "recap": _condense(section, recap_chars),
            "posts": posts,
        })

    return {"name": "ainews", "issues": issues, "raw_count": total_posts,
            "note": "", "stale_days": stale_days}


def fetch_techmeme(window_h: int = DEFAULT_WINDOW_H, limit: int = 25,
                   max_items: int = 10) -> dict:
    """交叉验证源。只留 AI 相关条目，不产出原帖链接。"""
    entries = fetch_rss(TECHMEME_FEED, limit=limit)
    if not entries:
        return {"name": "techmeme", "items": [], "raw_count": 0, "note": "RSS 抓取失败"}

    cutoff = datetime.now(timezone.utc) - timedelta(hours=window_h)
    items = []
    for e in entries:
        dt = parse_entry_date(e)
        if dt and dt < cutoff:
            continue
        title = getattr(e, "title", "") or ""
        summary = _plain(getattr(e, "summary", "") or "", 300)
        if not is_ai_relevant(title, summary):
            continue
        items.append({"title": title, "url": getattr(e, "link", "") or "",
                      "summary": summary,
                      "date": dt.strftime("%Y-%m-%d %H:%M") if dt else ""})
        if len(items) >= max_items:
            break
    return {"name": "techmeme", "items": items, "raw_count": len(items), "note": ""}


