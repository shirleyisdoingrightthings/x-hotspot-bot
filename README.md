# X Hotspot Bot

Daily AI community debate tracker on X (Twitter), surfacing core technical disagreements and top-cited original tweets to Feishu.

## Workflow

```text
Latent Space [AINews] Feed (544 X Accounts) + Techmeme Feed
  │
  ▼
1. Fetch & Rank (x_report.py --mode fetch)
  ├─ Check 30h freshness window & skip already-broadcast AINews issues (sent_urls.json)
  ├─ If no new un-broadcast issue exists, exit early with NO_TOPICS (zero token cost)
  ├─ Extract AI Twitter Recap, preserve Supportive / Neutral / Critical perspectives
  ├─ Rank original x.com status links by citation count in the daily recap
  └─ Cross-reference with Techmeme mainstream tech coverage
  │
  ▼
2. Draft Report (Scheduled Agent at 15:00 CST)
  ├─ Summarize 3–5 major community debates based on prompt.md
  ├─ Present both supporting and critical viewpoints with @handles
  └─ Attach the single most-cited x.com original post link per topic
  │
  ▼
3. Validate & Deliver (x_report.py --mode send)
  ├─ Enforce hard gate: reject draft if no valid x.com/<user>/status/<id> link is present
  ├─ Convert to Feishu card Markdown & auto-paginate if needed
  └─ Push to Feishu webhook & archive both tweet URLs and issue URLs for deduplication
```

## Operation

1. **Fetch Materials**: Run `bash claude_report.sh fetch` to gather the latest un-broadcast `[AINews]` recap and ranked X posts into `logs/last_context.txt`.
2. **Generate Draft**: If `FETCH_OK`, the agent reads `logs/last_context.txt` and `prompt.md`, writing the debate summary to `logs/report_draft.txt`.
3. **Send to Feishu**: Run `bash claude_report.sh send` to verify original tweet links and deliver the report to Feishu.
