# AI Scoring Harness & Personalized Outreach Engine

The intelligence layer uses **OpenRouter API** (`https://openrouter.ai/api/v1`) as a single unified LLM gateway:
- **Fast / Extraction Model**: `deepseek/deepseek-chat` (or `google/gemini-2.0-flash-001`) for rapid normalization and classification.
- **Reasoning & Drafting Model**: `deepseek/deepseek-chat` / `anthropic/claude-3.5-haiku` for deep candidate fit scoring and hyper-personalized outreach writing.

---

## 1. Candidate Profile & Resume Ingestion

The scoring engine evaluates every opportunity against your personal background:

1. **`profile/resume.pdf` / `resume.md`**: Automatically parsed to extract your career history, technical stack, concrete metrics, and past projects.
2. **`user_profile.yaml`**: Configures targeting parameters, core strengths, proof-of-work highlights, and writing style:

```yaml
candidate:
  full_name: "Anurag"
  email: "your.email@domain.com"
  linkedin: "https://linkedin.com/in/yourprofile"
  github: "https://github.com/yourusername"
  portfolio_url: "https://yourportfolio.dev"
  headline: "Backend & Systems Engineer specializing in distributed systems and LLM agent orchestration."
  
  core_skills:
    - "Python / FastAPI / AsyncIO"
    - "LangGraph / LLM Agent Workflows"
    - "Distributed Systems & Queues (Kafka, Redis, RabbitMQ)"
    - "PostgreSQL / SQLite performance optimization"
    - "Docker / Kubernetes / Cloud Infra"

  key_achievements:
    - "Architected a multi-agent orchestration pipeline cutting execution latency by 45%."
    - "Scaled a real-time event streaming pipeline processing 50k events/sec with 99.99% uptime."
    - "Created an open-source developer tool with 1,200+ GitHub stars."

targeting:
  target_stages: ["pre_seed", "seed", "series_a", "series_b", "series_c"]
  target_domains: ["AI & LLM Infra", "DevTools", "Distributed Systems", "B2B SaaS", "Fintech"]
  target_roles: ["Founding Engineer", "Senior Backend Engineer", "AI / Agent Systems Engineer"]
  location:
    remote_only: true
    prioritized_regions: ["India", "Remote Worldwide", "US", "Europe"]
  min_fit_score: 75
```

---

## 2. 0–100 Scoring Rubric

### A. For Early & Stealth Startups (Founder Reachout)
- **Domain & Mission Alignment (30%)**: Matches your target sectors (AI infra, devtools, distributed systems, fintech).
- **Tech Stack & Problem Synergy (30%)**: Matches your core technical skills (Python, LangGraph, agent orchestration, databases).
- **Growth & Backing Signal (25%)**: Top accelerator (YC), reputable venture backing (Sequoia, Benchmark, Founders Fund), or strong founder pedigree.
- **Stage & Team Fit (15%)**: 2–15 person founding team (Pre-Seed to Series C) where a high-impact cold pitch succeeds.

### B. For Active Job Postings (Role Application)
- **Hard Skill Overlap (35%)**: Direct match on required stack and technical architecture.
- **Seniority & Scope (25%)**: Aligned with target seniority (Senior / Lead / Founding).
- **Company Quality & Remote Fit (25%)**: Fully remote or location-compliant, stable funding.
- **Differentiating Edge (15%)**: Relevant open-source projects or domain achievements.

### Hard Knockout Criteria (Score = 0)
- ❌ Non-target stages (e.g. Series D+ conglomerates or unpaid student projects).
- ❌ Blacklisted sectors (gambling, crypto casinos, aggressive adtech).
- ❌ Mandatory on-site in unsupported locations.
- ❌ Company already contacted within the last 90 days.

---

## 3. Outreach Drafting Strategies

### Strategy 1: Founder Cold Pitch (Early-Stage Launch / Funding)
- **Subject**: Building [Feature/Infra] at [Company] / Congrats on [Milestone]
- **Structure**:
  1. Specific compliment referencing their Product Hunt launch, YC batch, or seed funding.
  2. 1–2 sentences on your background + **1 concrete achievement with metrics**.
  3. Specific technical observation on what they are building and how you can help build it.
  4. Low-friction CTA (<120 words total).

### Strategy 2: Stealth Venture Reachout
- **Subject**: [Domain] at [Company] / Connecting with [Founder Name]
- **Structure**:
  1. Acknowledge founder departure / stealth round.
  2. Pitch early technical collaboration in their domain.
  3. Share GitHub/portfolio link.

### Strategy 3: Job Application Pitch
- **Subject**: [Role Title] — [Candidate Name] — [Key Skill/Achievement]
- **Structure**:
  1. Direct, value-driven application pitch linking your proof of work to their specific requirements.

### Strategy 4: 2-Sentence Follow-Up Bump (Sent 5–7 Days Later)
- **Subject**: Re: [Original Subject]
- **Body**: *"Hi [Name], just bumping this in case it got buried in your inbox. Still would love to connect for 10 mins if you're exploring early engineering help at [Company]. Best, [Your Name]"*

---

## 4. Writing Style Rules & Anti-Patterns

- **Word Count**: Strictly between 75 and 120 words.
- **Tone**: Technical, peer-to-peer, direct, humble.
- **Anti-Patterns Enforced**:
  - 🚫 No generic sycophancy (*"I was amazed by your stellar journey..."*).
  - 🚫 No apologies for reaching out (*"Sorry to bother you..."*).
  - 🚫 No buzzwords (*"synergy"*, *"rockstar"*, *"ninja"*).
