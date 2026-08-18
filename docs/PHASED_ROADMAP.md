# Phased Execution Roadmap & Checkpoints

This document outlines the 6 atomic phases for building and verifying the Personal AI Startup & Job Outreach System.

---

## Roadmap Summary

| Phase | Description | Key Deliverables | Checkpoint Status |
| :--- | :--- | :--- | :--- |
| **Phase 1** | Foundation, DB Schema & Candidate Ingestion | Scaffolding, SQLite schema, `user_profile.yaml`, resume parser | Checkpoint 1 |
| **Phase 2** | Multi-Source Discovery Engine | Track A (Ashby/GH/Lever) + Track B (YC, PH, HN, India, SEC, Stealth) | Checkpoint 2 |
| **Phase 3** | AI Intelligence Engine | Scoring rubric, contact/LinkedIn research, specialized draft generator | Checkpoint 3 |
| **Phase 4** | LangGraph StateGraph & Safety Gate | `StateGraph`, `SqliteSaver` checkpointer, human `interrupt()`, SMTP node | Checkpoint 4 |
| **Phase 5** | Telegram Bot Controller | Rich cards, inline buttons, draft edit in chat, email input, follow-up check-in | Checkpoint 5 |
| **Phase 6** | Scheduler, Anti-Idle, Backups & Docker | APScheduler, 30s compute pulse, SQLite backups, multi-arch Docker | Checkpoint 6 |

---

## Phase 1: Foundation, DB Schema & Candidate Ingestion

### Goals:
Set up environment configuration, SQLite schema with deduplication, candidate profile loader (`user_profile.yaml`), resume parser (`profile/resume.pdf` / `resume.md`), and unit tests.

### Tasks:
- [ ] **1.1**: Create `requirements.txt`, `pyproject.toml`, `.env.example`, and `config.py` using Pydantic Settings.
- [ ] **1.2**: Create `db/schema.sql` and `db/database.py` with CRUD functions and deduplication logic (domain, posting URL, external ID).
- [ ] **1.3**: Create `user_profile.yaml` and `profile/parser.py` (supporting PDF and Markdown resume parsing).
- [ ] **1.4**: Unit tests for DB operations, profile loading, and resume parsing.

### 🏁 Checkpoint 1:
- DB initializes cleanly, stores sample test records, prevents duplicate insertions, and parses candidate profile and resume.

---

## Phase 2: Multi-Source Discovery Engine

### Goals:
Implement Track A (Job Boards) and Track B (Early & Stealth Startups, YC, Product Hunt, Launch HN, Indian Startups, SEC Form D, VC Stealth) connectors.

### Tasks:
- [ ] **2.1**: Define base connector interface and normalized models (`discovery/base.py`, `discovery/models.py`).
- [ ] **2.2**: Implement Track A connectors (`discovery/job_boards/ashby.py`, `greenhouse.py`, `lever.py`).
- [ ] **2.3**: Implement Track B launch connectors (`discovery/company_launch/yc_directory.py`, `producthunt.py`, `hackernews.py`, `funding_rss.py`).
- [ ] **2.4**: Implement Indian startup ecosystem connector (`discovery/company_launch/indian_startups.py` - Inc42, Entrackr, YourStory).
- [ ] **2.5**: Implement Stealth startup discovery (`discovery/company_launch/sec_edgar.py`, `vc_stealth.py`, `tavily_stealth.py`).
- [ ] **2.6**: Implement Curated Watchlist connector (`discovery/watchlist.py`).
- [ ] **2.7**: Build Discovery Coordinator (`discovery/manager.py`) with SQLite deduplication and rate limiting.

### 🏁 Checkpoint 2:
- CLI command `python -m cli test-discovery --source [yc|ph|hn|india|sec|ashby]` populates deduplicated opportunities into SQLite.

---

## Phase 3: AI Intelligence Engine

### Goals:
Implement LLM client, structured fit evaluation, contact enrichment (Tavily + Hunter/Apollo), and personalized draft generators.

### Tasks:
- [ ] **3.1**: Create LLM wrapper (`pipeline/llm.py`) using **OpenRouter API** (`https://openrouter.ai/api/v1` - OpenAI-compatible) with configurable models (`OPENROUTER_FAST_MODEL`, `OPENROUTER_SMART_MODEL`) and Pydantic structured output validation.
- [ ] **3.2**: Implement Fit Scoring Node (`pipeline/nodes/score_fit.py`) enforcing candidate criteria, target stages (Pre-Seed to Series C), remote/India focus, and knockout filters.
- [ ] **3.3**: Implement Contact Research & Verification Node (`pipeline/nodes/research_contacts.py`) fetching founder names, emails, confidence scores, and LinkedIn URLs.
- [ ] **3.4**: Implement Personalized Outreach Drafting Node (`pipeline/nodes/draft_outreach.py`) crafting specific founder pitches, stealth reachouts, job applications, and follow-up bumps.
- [ ] **3.5**: Unit tests with mock responses for scoring, contact extraction, and drafting.

### 🏁 Checkpoint 3:
- Given an opportunity, the pipeline scores fit (0–100), finds founder contact/LinkedIn info, and generates a personalized <120-word email.

---

## Phase 4: LangGraph StateGraph & Persistence Gate

### Goals:
Assemble the workflow in LangGraph with `SqliteSaver` checkpointer and `interrupt()` human-in-the-loop gate.

### Tasks:
- [ ] **4.1**: Define typed state schemas (`pipeline/state.py`).
- [ ] **4.2**: Build `StateGraph` in `pipeline/graph.py` linking enrichment -> scoring -> research -> drafting -> `interrupt()` -> delivery.
- [ ] **4.3**: Integrate `SqliteSaver` in `pipeline/orchestrator.py` for persistent state & zero-loss pausing.
- [ ] **4.4**: Implement Gmail SMTP email sender node (`pipeline/nodes/send_outreach.py`) recording sent metadata into `sent_history`.

### 🏁 Checkpoint 4:
- In `--dry-run` mode, the graph pauses at `human_gate`, writes state to SQLite, and resumes upon receiving `Command(resume=...)`.

---

## Phase 5: Interactive Telegram Bot Controller

### Goals:
Build the long-polling Telegram bot with rich preview cards, inline action buttons, direct-reply draft editing, manual email input, and follow-up check-ins.

### Tasks:
- [ ] **5.1**: Implement long-polling bot core (`bot/telegram_bot.py`).
- [ ] **5.2**: Render rich preview cards with score, company, milestone, LinkedIn URL, email confidence badge, and draft text.
- [ ] **5.3**: Implement inline button callback handlers (`Approve & Send`, `Edit Draft`, `Provide Email`, `Reject`, `Skip`).
- [ ] **5.4**: Implement text reply listener to capture edited draft text and provided emails directly in Telegram chat.
- [ ] **5.5**: Render 5–7 day follow-up check-in cards (`"Did you receive a reply?"` `[Yes]` `[No - Draft Bump]`).
- [ ] **5.6**: Implement bot commands (`/profile`, `/status`, `/discover`, `/set`).

### 🏁 Checkpoint 5:
- Full interactive loop tested via Telegram: receiving cards, editing text in chat, providing email, and approving dispatches.

---

## Phase 6: Scheduler, Anti-Idle Heartbeat, Backups & Oracle Cloud Deployment

### Goals:
Automated periodic jobs, Oracle Free Tier anti-idle keep-alive, SQLite backups, and production Docker containerization.

### Tasks:
- [ ] **6.1**: Configure APScheduler (`scheduler.py`) for discovery jobs, daily follow-up checks, and daily backups.
- [ ] **6.2**: Implement 30-second Oracle anti-idle compute/RAM pulse (`heartbeat.py`) running every 4 hours.
- [ ] **6.3**: Build FastAPI management server (`app.py`) and CLI suite (`cli.py`).
- [ ] **6.4**: Create multi-arch `Dockerfile` (`amd64`/`arm64`) and `docker-compose.yml` with persistent volume mounts.
- [ ] **6.5**: Create `README.md` and verification suite.

### 🏁 Checkpoint 6:
- `docker compose up -d` boots up cleanly, schedulers run, Telegram bot polls, health checks pass, and heartbeat logs verify active status.
