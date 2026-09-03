#!/bin/bash
# health_check.sh — X 热点 Bot
# 薄封装：设好本 bot 的差异点后，交给同级 shared/health_check_base.sh 执行。
# 完整流程与踩坑记录见那个文件，别把逻辑抄回来。

DIR="$(cd "$(dirname "$0")" && pwd)"

BOT_NAME="X 热点 Bot"
MAIN_PLIST="$HOME/Library/LaunchAgents/com.shirley.x-hotspot-bot.plist"

# 终态 WARN 的匹配模式。⚠️ 必须与 x_report.py 里 write_log("WARN", ...) 的实际措辞
# 一致——对不上就会把"正常的没东西可播"误判成缺跑，白派一次无头补跑。
NO_NEWS_PATTERN="没抓到可用素材"
NO_NEWS_MSG="今天窗口内没抓到可用素材，未出稿（非故障）"

# ⚠️ 本 bot 的键名没有 rss_ 前缀（x_report.py 写的是 stale_sources/zero_sources）。
# 抽公共层之前这里错抄成了 rss_*，导致零产告警从上线起就没触发过，2026-09-03 修。
STALE_KEY="stale_sources"
ZERO_KEY="zero_sources"

# 第 4 节：抓到的原帖数量异常偏低
content_check() {
    local posts
    posts=$(jsonl_field ainews_posts 99)
    if [ -n "$posts" ] && [ "$posts" -lt 3 ] 2>/dev/null; then
        notify WARN "本次仅抓到 ${posts} 条原帖，请检查 AINews provider"
        echo "[health_check] WARN: ainews_posts=${posts}，原帖数量异常偏低"
    fi
}

source "$DIR/../shared/health_check_base.sh"
