# Telegram Human-in-the-Loop Workflow

The Telegram Bot serves as the primary control center for reviewing matches, refining drafts, verifying contact emails, and managing follow-ups.

---

## 1. Zero Inbound Networking (Long-Polling)

- The bot runs using `python-telegram-bot` with **outbound long-polling** (`getUpdates`).
- **No public IP, port forwarding, webhook, or SSL certificate required**.
- Works behind any firewall or home router and connects directly from Oracle Cloud.

---

## 2. Opportunity Preview Card Layout

Every qualified opportunity (Fit Score $\ge$ 75) produces a structured interactive card:

```text
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
🔥 FOUNDER OUTREACH MATCH (Fit Score: 92/100)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

🏢 Company: CodeMorph AI
🌐 Website: https://codemorph.dev
📍 Location: Remote • Bangalore / San Francisco
🚀 Milestone: YC W25 • Raised $3.2M Seed (Benchmark)
👥 Target: Alex Rivera (Co-Founder & CTO)
🔗 LinkedIn: https://linkedin.com/in/alexrivera-tech
📧 Email: alex@codemorph.dev (Verified • 95% conf)

💡 Why It's a Fit:
• Building autonomous code refactoring agents in Python/Rust.
• 5-person founding team; no formal job board yet.
• Strong synergy with your AST & LLM workflow portfolio.

📝 Draft Outreach:
────────────────────────────────
Subject: Building CodeMorph's agent engine / Congrats on YC W25

Hi Alex,

Loved seeing CodeMorph's launch on HN yesterday—especially your approach to deterministic AST-based code transforms alongside LLMs.

I'm a backend/systems engineer specializing in Python and agent orchestration. Recently, I built an autonomous test generation pipeline that slashed regression debugging time by 40%.

I noticed you're scaling out the core transform engine post-Demo Day. I'd love to help build out your agent execution runtime and sandbox infrastructure.

Open to a 10-min intro chat sometime this week?

Best,
Anurag | github.com/anurag
────────────────────────────────
```

### Inline Action Buttons:
```
[ ✅ Approve & Send ]   [ ✏️ Edit Draft ]
[ ✍️ Provide Email ]   [ ❌ Reject ]
[ ⏭️ Skip ]
```

---

## 3. Contact Fallback & Email Confidence Badging

1. **High Confidence (`verified`)**:
   - `alex@domain.com (Verified • 95% conf)`
2. **Low Confidence / Pattern Guess (`low_confidence`)**:
   - `alex@domain.com (⚠️ Low Confidence / Pattern Guess)`
   - Founder's **LinkedIn profile link** is prominently displayed.
3. **Missing Email (`missing`)**:
   - `❌ Email Missing`
   - You can tap **`[ ✍️ Provide Email ]`** and reply with the verified email address (e.g. found on LinkedIn). The bot updates the database and card immediately.

---

## 4. Interactive Reply Handlers

- **Tapping `[ ✏️ Edit Draft ]`**:
  - The bot sends: *"Please reply with your updated draft body or instructions:"*
  - You reply in Telegram chat with your revised text.
  - The bot updates the SQLite record, renders the new card, and prompts for approval.
- **Tapping `[ ✍️ Provide Email ]`**:
  - The bot sends: *"Please reply with the email address for Alex Rivera:"*
  - You reply: `alex.rivera@codemorph.dev`
  - The bot updates contact record to verified and updates the preview card.
- **Tapping `[ ✅ Approve & Send ]`**:
  - Resumes the LangGraph thread via `Command(resume={"action": "approve"})`.
  - Dispatches email via Gmail SMTP.
  - Records timestamp in `sent_history`.
  - Updates Telegram card to `✅ Sent to alex@codemorph.dev at 16:30`.

---

## 5. 5–7 Day Follow-Up Check-in Flow

5–7 days after an email is sent, the daily scheduler checks `sent_history` and triggers a check-in card:

```text
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
📬 OUTREACH FOLLOW-UP CHECK-IN
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

🏢 Company: CodeMorph AI
👥 Contact: Alex Rivera (alex@codemorph.dev)
📅 Sent Date: 5 days ago (13 Aug)
📝 Original Subject: Building CodeMorph's agent engine

Did you receive a reply or schedule an intro?
```

### Follow-Up Buttons:
```
[ ✅ Got Reply / Interview ]
[ ❌ No Reply - Draft Follow-up ]
[ ⏭️ Snooze 3 Days ]
```

- **Tapping `[ ✅ Got Reply ]`**: Marks status as `replied / active conversation`.
- **Tapping `[ ❌ No Reply - Draft Follow-up ]`**: Prompts DeepSeek to generate a 2-sentence gentle bump and renders a follow-up approval card.

---

## 6. Telegram Management Commands

- `/profile` — View current candidate profile, target stages, and active filters.
- `/status` — View stats (Total Discovered, Evaluated, Approved, Sent, Pending).
- `/discover [yc|ph|hn|india|sec|ashby]` — Trigger an instant discovery scan.
- `/set stages pre_seed,seed,series_a` — Update stage targeting.
- `/set min_score 80` — Update minimum fit threshold.
- `/pause` / `/resume` — Toggle automated discovery jobs.
