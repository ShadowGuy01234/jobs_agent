# Job Outreach Agent

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Python 3.11+](https://img.shields.io/badge/python-3.11%2B-blue.svg)](pyproject.toml)
[![Tests](https://img.shields.io/badge/tests-pytest-0A9EDC.svg)](tests)

An autonomous, AI-powered outreach pipeline that discovers **active job postings, early-stage startups, and stealth ventures** (Pre-Seed to Series C, spanning Remote, Indian, and global tech hubs), scores each one against your profile, finds founder contacts and verified emails, drafts hyper-personalized cold outreach, and waits for your explicit approval on Telegram before sending anything.

This started as a personal job-search tool and is shared here as a working reference / portfolio project. Fork it, point it at your own profile, and run your own search. It's not a maintained product — issues and PRs are welcome, but there's no support guarantee.

---

## Contents

- [Features](#features)
- [Architecture](#architecture)
- [Getting Started](#getting-started)
- [Deployment](#deployment)
- [Telegram Bot Commands](#telegram-bot-commands)
- [Testing](#testing)
- [Documentation](#documentation)
- [License](#license)

---

## Features

- **Dual-track discovery** — Track A pulls active job openings from Ashby, Greenhouse, and Lever. Track B surfaces early-stage and stealth companies with no job posting yet, via YC batches, Product Hunt launches, Hacker News (`Launch HN` / `Show HN`), Indian startup media (Inc42, Entrackr, YourStory), SEC Form D filings, VC feeds, and Tavily search sweeps.
- **Multi-provider AI gateway** — TokenRouter as the primary gateway (`TOKENROUTER_API_KEY`), with drop-in support for OpenRouter (`OPENROUTER_API_KEY`) and Groq (`GROQ_API_KEY`) for scoring and drafting.
- **Human-in-the-loop send gate** — email delivery is isolated outside the autonomous agent graph. Nothing goes out until you tap **Approve & Send** in Telegram.
- **Automated follow-ups** — tracks sent emails and prompts a 5–7 day check-in on Telegram, generating a short follow-up draft on demand.
- **Contact enrichment with confidence badging** — surfaces founder LinkedIn profiles and flags pattern-guessed emails as low-confidence, with a manual override button.
- **Zero inbound ports** — the Telegram bot runs on long-polling, so deployment needs no public IP, domain, or SSL certificate.
- **Free-tier deployment ready** — Docker Compose setup with a built-in anti-idle heartbeat for Oracle Cloud's Always Free tier.

---

## Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                    Single Python Process                    │
│                                                               │
│   ┌──────────────────┐               ┌──────────────────┐   │
│   │   APScheduler    │               │   Telegram Bot   │   │
│   │ (Daily / 6-hour  │               │  (Long Polling)  │   │
│   │  discovery jobs) │               │                  │   │
│   └────────┬─────────┘               └────────┬─────────┘   │
│            │                                  │              │
│            ▼                                  │              │
│   ┌─────────────────────────────────────┐     │              │
│   │      LangGraph Orchestrator         │     │              │
│   │  1. Ingest & Deduplicate            │     │              │
│   │  2. AI Fit Scoring (0-100)          │     │              │
│   │  3. Tavily & Hunter Research        │     │              │
│   │  4. AI Draft Outreach               │     │              │
│   │  5. interrupt() [PAUSED]            │◄────┘              │
│   │     - Saves state to SQLite         │  (Tap "Approve")   │
│   │     - Pushes preview to Telegram    │                    │
│   │  6. Send Outreach (Only on resume)  │                    │
│   └──────────────────┬──────────────────┘                    │
│                       │                                      │
│                       ▼                                      │
│             ┌──────────────────┐                             │
│             │ SQLite Database  │                             │
│             │ (data/outreach.db)│                             │
│             └──────────────────┘                             │
└─────────────────────────────────────────────────────────────┘
```

See [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) for the full component breakdown.

---

## Getting Started

### Prerequisites

- Python 3.11+
- A Telegram bot token ([@BotFather](https://t.me/BotFather)) and your chat ID ([@userinfobot](https://t.me/userinfobot))
- An API key for at least one LLM gateway: [TokenRouter](https://tokenrouter.com), [OpenRouter](https://openrouter.ai), or [Groq](https://groq.com)
- A Gmail account with an [App Password](https://myaccount.google.com/apppasswords) for SMTP sending

### 1. Clone & install

```bash
git clone https://github.com/your-handle/jobs_agent.git
cd jobs_agent

python -m venv venv
source venv/bin/activate      # Windows: venv\Scripts\activate

pip install -r requirements.txt
```

### 2. Configure credentials

```bash
cp .env.example .env
```

Fill in `.env`:

| Variable | Purpose |
| :--- | :--- |
| `TOKENROUTER_API_KEY` | Primary LLM gateway key. |
| `OPENROUTER_API_KEY` / `GROQ_API_KEY` | Optional alternate gateways. |
| `TELEGRAM_BOT_TOKEN` / `TELEGRAM_CHAT_ID` | Bot auth and your chat for approvals. |
| `GMAIL_USER` / `GMAIL_APP_PASSWORD` | SMTP sending identity. |
| `TAVILY_API_KEY` | Optional — improves contact research. |
| `DRY_RUN` | Set `true` to simulate sends before going live. |

### 3. Set up your profile

```bash
cp user_profile.example.yaml user_profile.yaml
cp profile/resume.example.md profile/resume.md
```

Edit `user_profile.yaml` with your skills, quantified achievements, target funding stages, and target domains. Fill in `profile/resume.md` (or drop a `profile/resume.pdf` alongside it). Both files are gitignored, so your details never get committed.

### 4. Run locally

```bash
python -m cli init-db          # Initialize the database
python -m cli profile          # Sanity-check your profile
python -m cli discover --source yc --limit 5   # Test a discovery sweep

python app.py                  # Start the full server (FastAPI + Telegram + schedulers)
```

---

## Deployment

The recommended path is Docker Compose against any always-on Linux host; a native `systemd` alternative is also included. Full walkthrough with cost breakdown and Oracle Cloud specifics: [docs/DEPLOYMENT_AND_ORACLE.md](docs/DEPLOYMENT_AND_ORACLE.md).

### Docker Compose

```bash
git clone https://github.com/your-handle/jobs_agent.git
cd jobs_agent
cp .env.example .env && nano .env
cp user_profile.example.yaml user_profile.yaml && nano user_profile.yaml

docker compose up -d --build
docker compose logs -f
```

`docker-compose.yml` mounts `data/` for the SQLite database and backups, and mounts `user_profile.yaml` / `profile/` read-only so profile edits apply without a rebuild.

### Free-tier hosting (Oracle Cloud Always Free)

Because the bot uses Telegram long-polling and outbound-only SMTP, it needs no ingress rules, public IP, or TLS setup — it runs happily on Oracle Cloud's Always Free Ampere A1 or AMD micro instances at $0/month. A built-in heartbeat job (`heartbeat.py`, every 4 hours) keeps the instance's utilization metric above Oracle's idle-reclamation threshold. Setup steps and CI/CD auto-deploy config are in [docs/DEPLOYMENT_AND_ORACLE.md](docs/DEPLOYMENT_AND_ORACLE.md); the GitHub Actions workflow lives at [.github/workflows/deploy.yml](.github/workflows/deploy.yml).

### Native systemd (no Docker)

```bash
sudo cp systemd/job_outreach.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now job_outreach
sudo journalctl -u job_outreach -f
```

### Backups

The scheduler writes timestamped SQLite snapshots to `data/backups/`. Point any off-box sync tool (`rclone`, `rsync`, a private repo) at that directory to keep copies outside the host.

---

## Telegram Bot Commands

| Command / Action | Description |
| :--- | :--- |
| `/status` | View pipeline metrics (Discovered, Evaluated, Sent, Replies). |
| `/profile` | View candidate profile summary, target stages, and active filters. |
| `/discover [source]` | Trigger an on-demand discovery scan (`yc`, `producthunt`, `india`, `sec_edgar`, `ashby`). |
| `/set min_score [N]` | Update minimum fit score threshold (e.g. `/set min_score 80`). |
| `/dry_run [on\|off]` | Toggle simulated vs live Gmail SMTP sending. |
| **Approve & Send** | Dispatches email via Gmail SMTP and records in sent history. |
| **Edit Draft** | Reply with updated email text in Telegram chat. |
| **Provide Email** | Reply with verified email address for contact. |
| **Reject** | Rejects opportunity and archives. |

---

## Testing

```bash
pytest
```

---

## Documentation

- [System Architecture](docs/ARCHITECTURE.md)
- [Discovery Sources](docs/DISCOVERY_SOURCES.md)
- [Scoring Rubric & Drafting Engine](docs/SCORING_AND_OUTREACH.md)
- [Telegram Human-in-the-Loop Workflow](docs/TELEGRAM_WORKFLOW.md)
- [Deployment & Oracle Cloud Setup](docs/DEPLOYMENT_AND_ORACLE.md)
- [Phased Execution Roadmap](docs/PHASED_ROADMAP.md)

---

## License

MIT — see [LICENSE](LICENSE).
