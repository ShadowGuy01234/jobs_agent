# Multi-Source Discovery Engine

The system uses a **Dual-Track Discovery Architecture** to capture both active job postings and early-stage / stealth startups without public job listings.

---

## 1. Track A: Active Job Boards (Direct Public APIs)

We avoid fragile, ToS-violating HTML scraping by using clean public posting JSON APIs provided directly by major ATS platforms:

### 1.1 Ashby (`discovery/job_boards/ashby.py`)
- **API Endpoint**: `https://api.ashbyhq.com/posting-api/job-board/{organization_id}`
- **Payload**: Full structured JSON with title, description HTML/markdown, department, location, remote status, and compensation.
- **Why Ashby**: Primary ATS for fast-growing YC and AI startups (e.g. Linear, Cursor, Perplexity, Tavily).

### 1.2 Greenhouse (`discovery/job_boards/greenhouse.py`)
- **API Endpoint**: `https://boards-api.greenhouse.io/v1/boards/{board_token}/jobs?content=true`
- **Payload**: Structured JSON of all live roles with full job descriptions.

### 1.3 Lever (`discovery/job_boards/lever.py`)
- **API Endpoint**: `https://api.lever.co/v0/postings/{company}?mode=json`
- **Payload**: Clean JSON feed of open roles with categories and requirements.

---

## 2. Track B: Early & Stealth Startups (No Public Openings)

Startups at the Pre-seed, Seed, and Series A stages frequently need founding engineers or core contributors before they set up an ATS. We monitor 7 distinct data feeds:

### 2.1 Y Combinator Batches & Directory (`discovery/company_launch/yc_directory.py`)
- **Sources**: YC Startup Directory API, batch feeds (W24, S24, W25, F25), and Work at a Startup public index.
- **Signal**: ~250+ new startups per batch. 90% need founding engineers immediately post-funding.

### 2.2 Product Hunt Launches (`discovery/company_launch/producthunt.py`)
- **Sources**: Daily Product Hunt RSS / GraphQL API.
- **Signal**: Startups launching Day-0 or major 2.0 products with founder/maker profiles directly attached.

### 2.3 Hacker News (`Launch HN` & `Show HN`) (`discovery/company_launch/hackernews.py`)
- **Sources**: Official Hacker News Firebase API / Algolia Search.
- **Signal**: Posts authored directly by technical founders. Best signal for DevTools, AI infrastructure, and open-source ventures.

### 2.4 Indian Tech & Funding News (`discovery/company_launch/indian_startups.py`)
- **Sources**: Inc42, Entrackr, YourStory funding RSS feeds, and YC India cohort tracker.
- **Signal**: Newly funded Indian startups and cross-border US-India tech ventures.

### 2.5 SEC Form D Filings (`discovery/company_launch/sec_edgar.py`)
- **Sources**: Free SEC EDGAR API querying Form D (Regulation D exempt offering filings) for tech SIC codes.
- **Signal**: US tech startups closing stealth seed/series A funding rounds (legally required to file within 15 days, even before launching a website).

### 2.6 VC Portfolio Stealth Feeds (`discovery/company_launch/vc_stealth.py`)
- **Sources**: Portfolio update feeds from top venture firms: Sequoia/Peak XV, a16z, Benchmark, Founders Fund, Pear VC, Soma Capital.
- **Signal**: Startups publicly listed as *"Stealth — AI/DevTools [Founder Name]"*.

### 2.7 Tavily AI Stealth Sweeps (`discovery/company_launch/tavily_stealth.py`)
- **Queries**: Targeted search queries like:
  `site:linkedin.com/in ("Founder at Stealth" OR "Co-Founder at Stealth") ("AI" OR "Infrastructure") ("ex-Google" OR "ex-OpenAI" OR "ex-Stripe")`

---

## 3. Deduplication & SQLite Ingestion

Every discovered opportunity passes through `discovery/manager.py`:
- Checks `companies` and `opportunities` tables in SQLite.
- Deduplicates on: `domain`, `company_name`, `source_url`, and `external_id`.
- Rejects already contacted companies (90-day cooldown).
- Limits ingestion to maintain max 10 high-fit alerts/day.
