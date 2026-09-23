# 🎯 Personal AI Startup & Job Outreach System

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Python 3.11+](https://img.shields.io/badge/python-3.11%2B-blue.svg)](pyproject.toml)

An autonomous, cloud-AI-powered outreach pipeline that discovers **active job postings, early-stage startups, and stealth ventures** (Pre-Seed to Series C, focusing on **Remote & Indian Startups** as well as Global/US tech hubs), evaluates candidate fit against your resume and profile, finds founder contacts and verified emails, drafts hyper-personalized cold outreach (<120 words), and requires your approval via Telegram before any email is dispatched.

This started as my own job-search tool and is shared here as a working reference / portfolio project — fork it and point it at your own profile to run your own search. It's not a maintained product, but issues and PRs are welcome.

---

## 🌟 Key Highlights

- **Dual-Track Discovery**:
  - **Track A (Active Job Openings)**: Ashby, Greenhouse, Lever.
  - **Track B (Early Startups & Stealth — No Job Openings)**: YC Batches, Product Hunt Launches, Hacker News (`Launch HN`/`Show HN`), Indian Startups (Inc42, Entrackr, YourStory), SEC Form D filings, VC stealth feeds, and Tavily search sweeps.
- **Multi-Provider AI Gateway (TokenRouter / OpenRouter / Groq)**: Powered by `TOKENROUTER_API_KEY` for **GLM 5.3 Flash / Free** (`z-ai/glm-5.3-free`), with full support for OpenRouter (`OPENROUTER_API_KEY` for DeepSeek, Claude, Gemini) and Groq (`GROQ_API_KEY`).
- **Strict Human-in-the-Loop Gate**: Email delivery is completely isolated outside the autonomous agent graph. Sending only occurs when you explicitly tap `[ ✅ Approve & Send ]` on Telegram.
- **5–7 Day Follow-Up Check-ins**: Tracks sent emails and prompts you via Telegram: *"Did they reply?"* with 1-tap `[ ✅ Got Reply ]` or `[ ❌ No Reply - Draft Follow-up ]` (which generates a 2-sentence gentle bump).
- **Contact Fallback & Badging**: Prominently shows founder LinkedIn profile links and badges unverified emails with `⚠️ Low Confidence / Pattern Guess`, plus a `[ ✍️ Provide Email ]` button in Telegram.
- **Zero Inbound Ports (Telegram Long-Polling)**: Connects outbound to Telegram API. No public IP, domain, ngrok, SSL certs, or router port forwarding required.
- **Oracle Cloud Always Free Tier Ready**: Includes Docker Compose and an anti-idle heartbeat cron job to prevent VM reclamation.

---

## 🏗️ Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                    Single Python Process                    │
│                                                             │
│   ┌──────────────────┐               ┌──────────────────┐   │
│   │   APScheduler    │               │   Telegram Bot   │   │
│   │ (Daily / 6-hour  │               │  (Long Polling)  │   │
│   │  discovery jobs) │               │                  │   │
│   └────────┬─────────┘               └────────┬─────────┘   │
│            │                                  │             │
│            ▼                                  │             │
│   ┌─────────────────────────────────────┐     │             │
│   │      LangGraph Orchestrator         │     │             │
│   │  1. Ingest & Deduplicate            │     │             │
│   │  2. AI Fit Scoring (0-100)          │     │             │
│   │  3. Tavily & Hunter Research        │     │             │
│   │  4. AI Draft Outreach               │     │             │
│   │  5. interrupt() [PAUSED]            │◄────┘             │
│   │     - Saves state to SQLite         │  (Tap "Approve")  │
│   │     - Pushes preview to Telegram    │                   │
│   │  6. Send Outreach (Only on resume)  │                   │
│   └──────────────────┬──────────────────┘                   │
│                      │                                      │
│                      ▼                                      │
│            ┌──────────────────┐                             │
│            │ SQLite Database  │                             │
│            │ (data/outreach.db│                             │
│            └──────────────────┘                             │
└─────────────────────────────────────────────────────────────┘
```

---

## 🚀 Quickstart Guide

### 1. Clone & Install
```bash
git clone https://github.com/your-username/job_outreach.git
cd job_outreach

# Create virtualenv
python -m venv venv
# Linux / macOS:
source venv/bin/activate
# Windows:
venv\Scripts\activate

pip install -r requirements.txt
```

### 2. Configure Credentials (`.env`)
```bash
cp .env.example .env
```
Fill in the following key variables in `.env`:
- `TOKENROUTER_API_KEY`: Your TokenRouter API key (default endpoint for GLM 5.3 Flash/Free).
- `OPENROUTER_API_KEY`: (Optional) OpenRouter API key.
- `GROQ_API_KEY`: (Optional) Groq API key for fast inference.
- `TELEGRAM_BOT_TOKEN`: From [@BotFather](https://t.me/BotFather).
- `TELEGRAM_CHAT_ID`: Your personal Telegram chat ID (get via [@userinfobot](https://t.me/userinfobot)).
- `GMAIL_USER`: Your Gmail address.
- `GMAIL_APP_PASSWORD`: 16-character Google App Password from [Google Security Settings](https://myaccount.google.com/apppasswords).
- `TAVILY_API_KEY`: Optional but recommended for search & LinkedIn discovery.
- `DRY_RUN`: Set to `true` initially to simulate sending without real dispatch.

### 3. Customize Your Profile (`user_profile.yaml` & `profile/resume.md`)
```bash
cp user_profile.example.yaml user_profile.yaml
cp profile/resume.example.md profile/resume.md
```
- Update `user_profile.yaml` with your core skills, achievements with metrics, target stages (e.g. `pre_seed` to `series_c`), and target domains.
- Fill in `profile/resume.md`, or drop a `profile/resume.pdf` alongside it.
- Both `user_profile.yaml` and `profile/resume.md` are gitignored so your personal details never get committed.

### 4. Run Locally
```bash
# Initialize database
python -m cli init-db

# Check profile
python -m cli profile

# Test discovery sweep
python -m cli discover --source yc --limit 5

# Start full server (FastAPI + Telegram Polling + Schedulers)
python app.py
```

---

## ☁️ Deploying on Oracle Cloud Always Free Tier (24/7 Uptime for $0/mo)

1. Launch an **Ubuntu 22.04 / 24.04** VM (Ampere A1 ARM or AMD Micro) on Oracle Cloud Free Tier.
2. SSH into your VM and run:
   ```bash
   sudo apt update && sudo apt install -y docker.io docker-compose-v2 git
   sudo systemctl enable --now docker
   sudo usermod -aG docker $USER
   ```
3. Clone and start:
   ```bash
   git clone https://github.com/your-username/job_outreach.git
   cd job_outreach
   cp .env.example .env
   nano .env
   docker compose up -d --build
   ```
4. View live logs:
   ```bash
   docker compose logs -f
   ```

*Note: The built-in anti-idle heartbeat runs every 4 hours to keep Oracle's average utilization metric active, preventing free VM reclamation.*

---

## 📱 Telegram Bot Commands & Interactions

| Command / Action | Description |
| :--- | :--- |
| `/status` | View pipeline metrics (Discovered, Evaluated, Sent, Replies). |
| `/profile` | View candidate profile summary, target stages, and active filters. |
| `/discover [source]` | Trigger an on-demand discovery scan (`yc`, `producthunt`, `india`, `sec_edgar`, `ashby`). |
| `/set min_score [N]` | Update minimum fit score threshold (e.g. `/set min_score 80`). |
| `/dry_run [on\|off]` | Toggle simulated vs live Gmail SMTP sending. |
| **`[ ✅ Approve & Send ]`** | Dispatches email via Gmail SMTP and records in sent history. |
| **`[ ✏️ Edit Draft ]`** | Reply with updated email text in Telegram chat. |
| **`[ ✍️ Provide Email ]`** | Reply with verified email address for contact. |
| **`[ ❌ Reject ]`** | Rejects opportunity and archives. |

---

## 🧪 Testing

Run all unit tests across the entire 6-phase suite:
```bash
pytest
```

---

## 📄 Documentation

- [System Architecture](docs/ARCHITECTURE.md)
- [Discovery Sources](docs/DISCOVERY_SOURCES.md)
- [Scoring Rubric & Drafting Engine](docs/SCORING_AND_OUTREACH.md)
- [Telegram Human-in-the-Loop Workflow](docs/TELEGRAM_WORKFLOW.md)
- [Deployment & Oracle Cloud Setup](docs/DEPLOYMENT_AND_ORACLE.md)
- [Phased Execution Roadmap](docs/PHASED_ROADMAP.md)

---

## 📄 License

MIT — see [LICENSE](LICENSE).
