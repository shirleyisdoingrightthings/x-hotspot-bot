# X 热点 Bot — Claude Code 专属上下文

> 完整操作手册见 [`AGENTS.md`](./AGENTS.md)（通用，适用于所有 AI 工具）。
> 本文件只记录 Claude Code 专属的额外指令。

---

## 必读顺序

1. 先读 `AGENTS.md` — 获取完整架构、不变量、踩过的坑
2. 再读 `README.md` — 数据源为什么这么选（含已验证不可用的源清单）
3. 最后读本文件 — 获取 Claude 专属行为指令

---

## Claude 专属指令

### 自动加载行为
Claude Code 打开此目录时，自动加载本文件。请同时主动读取：
- `AGENTS.md`（完整上下文与不变量）
- `logs/run.log`（最近运行状态）
- `changelog.md`（当前已知问题，如存在）

### 运行约定（Option B）
- 当前定时调度与开机唤醒补跑均由 Antigravity Sidecar（每天 08:30）负责；`launchd`（09:30）仅保留轻量化健康检查与 Level 1 重发兜底（不再拉起无头 CLI）。

### 这个 bot 的四条红线（改动前先读 AGENTS.md 的完整说明）
1. **send 的原帖闸门不能放宽**——稿件里没有 `x.com/<user>/status/<id>` 就必须 `[FAIL]` 拒发。
   一份只有转述、没有现场的 X 播报价值等于零，这是它存在的理由。
2. **时效窗口 48 小时**，不是 24。要调走 `X_BOT_WINDOW_H` 环境变量，别改代码默认值。
3. **「被引用次数」不是点赞数**，任何面向读者的文案都不许把它写成互动量。
4. **provider 失效要吵，不要静默降级**。别加"一个源挂了自动换另一个"的回退。

### 改 `sources.py` 之后必须自测
解析逻辑对 AINews 的 HTML 结构很敏感，改完跑这个确认 `context` 没有变空：

```bash
/usr/bin/python3 -c "
import sys; sys.path.insert(0,'.')
import sources
iss = sources.fetch_ainews()['issues'][0]
print('空 context:', sum(1 for p in iss['posts'] if not p['context']), '/', len(iss['posts']))"
```

预期是 `0 / N`。出现非零就是链接标记又被 `TAG_RE` 吃掉了，回 `AGENTS.md` 看那一节。

### 对话风格
- 回复使用中文
- 代码改动前先说明改动范围和理由
- 不确定时主动说明，不要猜测后直接修改
