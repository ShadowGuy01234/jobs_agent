-- SQLite Schema for Personal AI Startup & Job Outreach System

PRAGMA foreign_keys = ON;
PRAGMA journal_mode = WAL;

CREATE TABLE IF NOT EXISTS companies (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    domain TEXT UNIQUE,
    name TEXT NOT NULL,
    website TEXT,
    stage TEXT DEFAULT 'unknown',
    source TEXT NOT NULL,
    description TEXT,
    tech_stack TEXT, -- JSON array of strings
    funding_info TEXT,
    country TEXT,
    is_stealth BOOLEAN DEFAULT 0,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS opportunities (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    company_id INTEGER REFERENCES companies(id) ON DELETE CASCADE,
    type TEXT NOT NULL, -- 'founder_reachout', 'stealth_reachout', 'job_posting'
    title TEXT NOT NULL,
    url TEXT UNIQUE,
    external_id TEXT,
    location TEXT,
    is_remote BOOLEAN DEFAULT 1,
    raw_content TEXT,
    status TEXT DEFAULT 'discovered', -- 'discovered', 'evaluated', 'filtered', 'drafted', 'pending_approval', 'approved', 'rejected', 'sent', 'failed'
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS contacts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    company_id INTEGER REFERENCES companies(id) ON DELETE CASCADE,
    name TEXT NOT NULL,
    title TEXT,
    email TEXT,
    email_confidence TEXT DEFAULT 'missing', -- 'verified', 'low_confidence', 'missing', 'manual'
    linkedin_url TEXT,
    twitter_url TEXT,
    source TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS evaluations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    opportunity_id INTEGER UNIQUE REFERENCES opportunities(id) ON DELETE CASCADE,
    fit_score INTEGER NOT NULL,
    decision TEXT NOT NULL, -- 'PROCEED', 'DROP'
    summary_reasoning TEXT,
    key_synergies TEXT, -- JSON array
    potential_risks TEXT, -- JSON array
    personalized_hook TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS outreach_drafts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    opportunity_id INTEGER REFERENCES opportunities(id) ON DELETE CASCADE,
    contact_id INTEGER REFERENCES contacts(id) ON DELETE SET NULL,
    draft_type TEXT DEFAULT 'initial', -- 'initial', 'follow_up'
    subject TEXT NOT NULL,
    body TEXT NOT NULL,
    status TEXT DEFAULT 'pending', -- 'pending', 'approved', 'edited', 'rejected', 'sent'
    revision_notes TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS sent_history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    opportunity_id INTEGER REFERENCES opportunities(id) ON DELETE CASCADE,
    draft_id INTEGER REFERENCES outreach_drafts(id) ON DELETE SET NULL,
    contact_id INTEGER REFERENCES contacts(id) ON DELETE SET NULL,
    recipient_email TEXT NOT NULL,
    subject TEXT NOT NULL,
    body TEXT NOT NULL,
    sent_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    follow_up_status TEXT DEFAULT 'pending_check', -- 'pending_check', 'replied', 'bump_drafted', 'bump_sent', 'closed'
    last_follow_up_check TIMESTAMP,
    notes TEXT
);

CREATE TABLE IF NOT EXISTS audit_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    event_type TEXT NOT NULL,
    message TEXT NOT NULL,
    payload TEXT, -- JSON string
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Indices for performance & deduplication
CREATE INDEX IF NOT EXISTS idx_companies_domain ON companies(domain);
CREATE INDEX IF NOT EXISTS idx_opportunities_url ON opportunities(url);
CREATE INDEX IF NOT EXISTS idx_opportunities_status ON opportunities(status);
CREATE INDEX IF NOT EXISTS idx_contacts_company_id ON contacts(company_id);
CREATE INDEX IF NOT EXISTS idx_evaluations_opp_id ON evaluations(opportunity_id);
CREATE INDEX IF NOT EXISTS idx_drafts_opp_id ON outreach_drafts(opportunity_id);
CREATE INDEX IF NOT EXISTS idx_sent_history_status ON sent_history(follow_up_status);
CREATE INDEX IF NOT EXISTS idx_sent_history_sent_at ON sent_history(sent_at);
