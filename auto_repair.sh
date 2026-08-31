#!/bin/bash
# auto_repair.sh — X 热点 Bot
# 检测到 [FAIL] 时由 health_check.sh 触发
# 修复逻辑统一维护在同级 shared/auto_repair_base.sh（路径由 $DIR 相对推导）

DIR="$(cd "$(dirname "$0")" && pwd)"
BOT_NAME="X 热点 Bot"
SCRIPT="$DIR/x_report.py"
ERROR="${1:-unknown error}"
DRAFTS="logs/report_draft.txt"

source "$DIR/../shared/auto_repair_base.sh"
