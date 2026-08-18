# System Architecture & Technical Design

A personal, cloud-AI-powered autonomous outreach system that discovers promising startups and job openings, evaluates fit against your profile, discovers founder/hiring contacts, drafts hyper-personalized outreach, and requires your explicit approval via Telegram before sending.

---

## 1. System Overview & Principles

1. **Precision Over Volume**: Max 10 highly curated alerts per day rather than generic mass cold emailing.
2. **Strict Human Gate**: The email delivery tool is isolated outside the autonomous agent's toolset. It only executes when you explicitly tap `[ ✅ Approve & Send ]` on Telegram via `Command(resume=...)`.
3. **Dual-Track Discovery**:
   - **Track A (Active Job Openings)**: Ashby, Greenhouse, Lever.
   - **Track B (Early Startups & Launches — No Job Openings)**: YC Batches, Product Hunt Launches, Hacker News (`Launch HN`/`Show HN`), Funding RSS (TechCrunch, Inc42, Entrackr), SEC Form D filings, VC stealth additions, and Tavily search sweeps.
4. **Zero Inbound Port Requirement**: Uses Telegram Long-Polling (`getUpdates`), making only outbound HTTPS requests. Runs securely behind any home router, firewall, or cloud security list without port forwarding or public domain setup.
5. **Oracle Cloud Free Tier Ready**: Multi-arch Docker (`amd64`/`arm64`) with persistent SQLite volume and an anti-idle heartbeat cron job.

---

## 2. End-to-End Architecture Diagram

```mermaid
flowchart TD
    subgraph Sched ["APScheduler / Cron / Heartbeat"]
        T["Trigger Discovery Run (Max 10 alerts/day)"]
        HB["Anti-Idle Heartbeat Job (Oracle Keep-Alive)"]
        FU["Follow-Up Check (5-7 Days Post-Send)"]
    end

    subgraph Profile ["User Profile & Resume Ingestion"]
        P1["user_profile.yaml (Target stages Pre-Seed to Series C, Remote + India Focus)"]
        P2["profile/resume.pdf or resume.md (Skills & Proof of Work)"]
    end

    subgraph TrackA ["Track A: Active Job Boards"]
        D1["Ashby API"]
        D2["Greenhouse API"]
        D3["Lever API"]
    end

    subgraph TrackB ["Track B: Early & Stealth Startups (No Openings)"]
        D4["YC Directory & Batches"]
        D5["Product Hunt Launches"]
        D6["Hacker News (Launch HN & Show HN)"]
        D7["Funding RSS (TechCrunch, Inc42, Entrackr, StrictlyVC)"]
        D8["SEC Form D Filings (EDGAR API)"]
        D9["VC Portfolio Stealth Feeds"]
        D10["Tavily AI Stealth Sweeps"]
    end

    subgraph LangGraph ["LangGraph StateGraph Workflow"]
        N1["1. Ingest & Deduplicate in SQLite"]
        N2{"Opportunity Type?"}
        N3A["2A. Score Job Fit vs Profile"]
        N3B["2B. Score Startup Fit & Value-Add"]
        N4["3. Research Contacts, Emails & LinkedIn<br/>Tavily + Hunter / Apollo"]
        N5A["4A. Draft Job Application Outreach"]
        N5B["4B. Draft Founder Cold Pitch<br/>Referencing launch / stealth / milestones"]
        N6["5. interrupt(human_review)<br/>Pauses & saves state in SQLite"]
    end

    subgraph Telegram ["Telegram Interface"]
        TB["Telegram Bot Card Preview<br/>Score, Company, Contact, LinkedIn & Draft"]
        U["User on Telegram<br/>Approve / Edit / Reject / Provide Email"]
        FC["Telegram Follow-Up Check-in<br/>'Did they reply?' [Yes] [No - Draft Bump]"]
    end

    subgraph Execution ["Gated Delivery & Tracking"]
        N7["6. Send Outreach<br/>Primary Gmail via SMTP"]
        DB[("SQLite DB & LangGraph SqliteSaver")]
        BK["Daily Backup Task"]
    end

    T --> TrackA
    T --> TrackB
    TrackA --> N1
    TrackB --> N1
    P1 & P2 -.-> N3A & N3B & N5A & N5B
    N1 --> N2
    N2 -->|Job Posting| N3A --> N4 --> N5A --> N6
    N2 -->|Early or Stealth Startup| N3B --> N4 --> N5B --> N6
    N6 -.->|Notification & Inline Keyboard| TB
    TB <-->|Review / Modify / Provide Email| U
    U -->|Tap Approve| TB
    TB -->|graph.stream Command resume=...| N7
    N7 --> DB
    N6 --> DB
    DB --> BK

    FU -->|Query 5+ days sent| DB
    DB -.->|Trigger Check-in Card| FC
    FC <-->|Check-in response| U
```

---

## 3. Core Technical Stack

- **Runtime & Orchestration**: Python 3.11+, LangGraph `StateGraph`, `SqliteSaver` checkpointer.
- **AI Gateway**: **OpenRouter API** (`https://openrouter.ai/api/v1` - OpenAI-compatible interface).
  - Fast extraction/classification model: `deepseek/deepseek-chat` (or `google/gemini-2.0-flash-001`)
  - Deep scoring & drafting model: `deepseek/deepseek-chat` (or `anthropic/claude-3.5-haiku` / `meta-llama/llama-3.3-70b-instruct`)
- **Web & Search**: `httpx`, `beautifulsoup4`, `feedparser`, Tavily API.
- **Enrichment**: Hunter.io / Apollo free tier + Tavily Search.
- **Database**: SQLite with WAL mode (`data/outreach.db`).
- **Telegram Bot**: `python-telegram-bot` in long-polling mode (`getUpdates`).
- **Email Delivery**: Primary Gmail via SMTP (TLS / SSL with App Password).
- **Scheduling**: APScheduler (Discovery, Follow-up checker, Anti-idle heartbeat, DB backups).
- **Server**: FastAPI with Uvicorn (Healthcheck and manual trigger API).
- **Deployment**: Multi-arch Docker (`amd64`/`arm64`) + Docker Compose / Systemd.
