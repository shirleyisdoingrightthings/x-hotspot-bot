#!/usr/bin/python3
"""
X 热点播报

每天把 X（Twitter）上 AI 圈在吵什么整理成一份播报，**每条话题都带讨论度最高的原帖直链**，
由 Claude 写稿后推送到飞书。本脚本只负责抓取与推送，不含写稿用的第三方大模型 API。

两种运行模式（--mode，均零 API 成本）：
- fetch：跑 provider 取材 → 把 context 打到 stdout（供 Claude routine 读取写稿）
- send ：读取 Claude 写好的稿子文件 → 清洗 HTML → 推送飞书 + 写日志

取材层在同目录 sources.py（provider 可插拔，换源不用动本文件）。
写稿规范在同目录 prompt.md，由 Claude routine 读取。

与另外三个 bot 的两点差别，改动时别抹平：
1. **时效窗口 48 小时**，不是 24。X 上一条帖子的讨论常要发酵一两天才到顶，
   24h 会把「昨天发、今天才吵起来」的话题整个漏掉。
2. **去重键是 x.com 原帖 URL**，不是文章 URL。同一个话题连着两天上榜没关系
   （讨论在演进），但同一条原帖不该被反复当成新料播两次。
"""

import argparse
import json
import os
import sys
import time
from datetime import datetime
from pathlib import Path

# 共享工具库：从脚本自身位置推导（bot 目录的同级 shared/），
# 整个 bots 文件夹搬到任何位置都不用改路径
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "shared"))
from bot_utils import (already_ran_today, load_sent_urls, url_key,
                       update_zero_streak, make_logger, make_pending_saver,
                       proxy_ok, emit_fetch_output, send_x_linked_report)

import sources

BASE = Path(__file__).parent
LOG_FILE = BASE / "logs" / "run.log"
JSONL_FILE = BASE / "logs" / "run.jsonl"
LOG_FILE.parent.mkdir(exist_ok=True)
CACHE_FILE = BASE / "pending_messages.json"
DRAFT_FILE = BASE / "logs" / "report_draft.txt"
FETCH_META = BASE / "logs" / "fetch_meta.json"
LAST_CONTEXT = BASE / "logs" / "last_context.txt"
SENT_URLS = BASE / "logs" / "sent_urls.json"
ZERO_STREAK = BASE / "logs" / ".zero_streak.json"
ZERO_STREAK_THRESHOLD = 3

# 启用哪些 provider，逗号分隔。默认 ainews 打底 + techmeme 交叉验证。
# 日后接了第三方 X API，把 twitterapi 加进来即可。
ENABLED = [p.strip() for p in
           os.getenv("X_BOT_PROVIDERS", "ainews,techmeme").split(",") if p.strip()]
WINDOW_H = int(os.getenv("X_BOT_WINDOW_H", str(sources.DEFAULT_WINDOW_H)))

FEISHU_WEBHOOK = os.getenv("FEISHU_WEBHOOK", "")
FEISHU_SECRET = os.getenv("FEISHU_SECRET") or None

write_log = make_logger(LOG_FILE, JSONL_FILE)
save_pending = make_pending_saver(CACHE_FILE)
_PROXY = os.getenv("HTTPS_PROXY") or os.getenv("HTTP_PROXY")


def _proxy_ok() -> bool:
    """代理预检 + 端口自愈，实现见 shared/bot_utils.proxy_ok。"""
    global _PROXY
    ok, _PROXY = proxy_ok(_PROXY, None)
    return ok


# ===== 抓取阶段 =====

def gather() -> tuple:
    """跑所有启用的 provider，返回 (context 文本, metrics, zero_sources)。
    进度打到 stderr，让 fetch 模式的 stdout 只保留干净的 context。"""
    print(f"📡 provider: {', '.join(ENABLED)}（窗口 {WINDOW_H}h）", file=sys.stderr)
    seen = load_sent_urls(SENT_URLS)
    lines, metrics, zero = [], {}, []

    # ---------- ainews（主力：原帖 + 讨论度）----------
    if "ainews" in ENABLED:
        try:
            r = sources.fetch_ainews(window_h=WINDOW_H)
        except Exception as exc:
            r = {"name": "ainews", "issues": [], "raw_count": 0,
                 "note": f"异常：{exc}", "stale_days": None}
        kept_posts = 0
        if r["issues"]:
            lines.append("=== AINEWS_BEGIN ===")
            if r.get("stale_days"):
                lines.append(f"⚠️ 窗口内没有新一期，以下是最新的一期，距今 {r['stale_days']} 天。"
                             f"写稿时必须向读者说明素材日期，不要写成「今天」。")
            for iss in r["issues"]:
                lines.append(f"\n----- 期次：{iss['date']} {iss['title']} -----")
                lines.append(f"原文：{iss['url']}")
                if iss["outline"]:
                    lines.append("覆盖面：" + " / ".join(iss["outline"]))
                lines.append("\n[Twitter Recap 正文]")
                lines.append(iss["recap"])
                lines.append("\n[原帖排行 · 按被引用次数，非真实互动量]")
                for i, p in enumerate(iss["posts"], 1):
                    fresh = "" if url_key(p["url"]) not in seen else "（已播过，勿作为新料）"
                    if not fresh:
                        kept_posts += 1
                    lines.append(f"{i}. [{p['mentions']} 次] @{p['handle']} {p['url']} {fresh}")
                    if p["context"]:
                        lines.append(f"   上下文：{p['context']}")
            lines.append("=== AINEWS_END ===")
        metrics["ainews_posts"] = r["raw_count"]
        metrics["ainews_fresh"] = kept_posts
        metrics["ainews_stale_days"] = r.get("stale_days")
        if not r["issues"]:
            zero.append("ainews")
        print(f"  ✓ ainews：{len(r['issues'])} 期 · {r['raw_count']} 条原帖"
              f"（新 {kept_posts}）{' ' + r['note'] if r['note'] else ''}", file=sys.stderr)

    # ---------- techmeme（交叉验证）----------
    if "techmeme" in ENABLED:
        try:
            m = sources.fetch_techmeme(window_h=WINDOW_H)
        except Exception as exc:
            m = {"name": "techmeme", "items": [], "raw_count": 0, "note": f"异常：{exc}"}
        if m["items"]:
            lines.append("\n=== TECHMEME_BEGIN ===")
            lines.append("（主流科技媒体同期报道，用来判断上面的话题是不是只在小圈层里热）")
            for it in m["items"]:
                lines.append(f"- {it['date']}  {it['title']}\n  {it['url']}")
            lines.append("=== TECHMEME_END ===")
        metrics["techmeme_items"] = m["raw_count"]
        if not m["items"]:
            zero.append("techmeme")
        print(f"  ✓ techmeme：{m['raw_count']} 条"
              f"{' ' + m['note'] if m['note'] else ''}", file=sys.stderr)

    # ---------- 其他 provider（如 twitterapi）----------
    for name in ENABLED:
        if name in ("ainews", "techmeme"):
            continue
        fn = sources.PROVIDERS.get(name)
        if fn is None:
            print(f"  ⚠️ 未知 provider：{name}（已跳过）", file=sys.stderr)
            continue
        try:
            fn(window_h=WINDOW_H)
        except NotImplementedError as exc:
            print(f"  ⚠️ provider {name} 未接入：{exc}", file=sys.stderr)
        except Exception as exc:
            print(f"  ⚠️ provider {name} 异常：{exc}", file=sys.stderr)

    return "\n".join(lines), metrics, zero


def _load_streak() -> dict:
    try:
        return json.loads(ZERO_STREAK.read_text(encoding="utf-8"))
    except Exception:
        return {}


# ===== 模式 1：fetch =====

def run_fetch() -> int:
    if already_ran_today(LOG_FILE):
        print("=== SKIP_ALREADY_RAN ===")
        return 0

    if not _proxy_ok():
        print(f"=== SKIP_PROXY === {_PROXY}")
        return 0

    context, metrics, zero_sources = gather()

    if not context.strip():
        print("=== NO_TOPICS ===")
        write_log("WARN", f"窗口 {WINDOW_H}h 内没抓到可用素材，未发送")
        return 0

    stale = update_zero_streak(ZERO_STREAK, zero_sources, list(ENABLED),
                               threshold=ZERO_STREAK_THRESHOLD)
    streak_now = _load_streak()
    for name in ENABLED:
        n = streak_now.get(name, 0)
        flag = f"  ⚠️ 零产（连续 {n} 天）" if name in zero_sources else ""
        print(f"   {name:12s}{flag}", file=sys.stderr)

    log_summary = (f"原帖 {metrics.get('ainews_posts', 0)} 条"
                   f"（新 {metrics.get('ainews_fresh', 0)}）"
                   f" + Techmeme {metrics.get('techmeme_items', 0)} 条")
    FETCH_META.write_text(json.dumps(
        {"log_summary": log_summary,
         "metrics": {**metrics, "zero_sources": zero_sources,
                     "stale_sources": stale, "window_h": WINDOW_H,
                     "providers": ENABLED}},
        ensure_ascii=False), encoding="utf-8")

    out = ["=== FETCH_OK ===",
           f"今天日期：{datetime.now().strftime('%Y-%m-%d')}",
           f"时效窗口：{WINDOW_H} 小时 ｜ provider：{', '.join(ENABLED)}",
           log_summary]
    if zero_sources:
        out.append(f"零产源：{', '.join(zero_sources)}")
    if stale:
        out.append("=== SOURCE_ALERT ===")
        for name, n in stale.items():
            out.append(f"{name} 已连续 {n} 天零产，检查该 provider 是否失效"
                       f"（sources.py 顶部有已验证不可用的源清单）")
        out.append("=== SOURCE_ALERT_END ===")
    out += ["=== CONTEXT_BEGIN ===", context, "=== CONTEXT_END ==="]
    emit_fetch_output(out, LAST_CONTEXT)
    return 0


# ===== 模式 2：send =====

def run_send(draft_path: Path) -> int:
    # 发送流程与 ai-builder-bot 完全一致，统一在 bot_utils.send_x_linked_report，
    # 其中含出稿硬闸门：稿件必须带 x.com 原帖直链，否则拒发。
    return send_x_linked_report(
        draft_path,
        log_file=LOG_FILE, cache_file=CACHE_FILE, fetch_meta=FETCH_META,
        sent_urls=SENT_URLS, webhook=FEISHU_WEBHOOK, secret=FEISHU_SECRET,
        write_log=write_log, save_pending=save_pending,
        link_label="原帖")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="X 热点播报")
    parser.add_argument("--mode", choices=["fetch", "send"], required=True,
                        help="fetch=取材并输出 context（供 Claude 写稿，零 API）"
                             " / send=发送 Claude 写好的稿子")
    parser.add_argument("--draft", default=str(DRAFT_FILE),
                        help="send 模式读取的稿件路径")
    args = parser.parse_args()
    sys.exit(run_fetch() if args.mode == "fetch" else run_send(Path(args.draft)))
