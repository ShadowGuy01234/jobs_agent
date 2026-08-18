"""SQLite Database manager with WAL mode, deduplication, and transactional helpers."""

import json
import sqlite3
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from config import settings


def get_db_connection(db_path: Optional[Path] = None) -> sqlite3.Connection:
    """Create and return a configured SQLite connection."""
    target_path = db_path or settings.DATABASE_PATH
    target_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(target_path), timeout=30.0)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON;")
    conn.execute("PRAGMA journal_mode = WAL;")

    # Auto-initialize schema if tables do not exist
    cursor = conn.cursor()
    cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='companies'")
    if not cursor.fetchone():
        schema_path = settings.BASE_DIR / "db" / "schema.sql"
        if schema_path.exists():
            with open(schema_path, "r", encoding="utf-8") as f:
                conn.executescript(f.read())
            conn.commit()

    return conn


def init_db(db_path: Optional[Path] = None) -> None:
    """Initialize database schema from schema.sql."""
    schema_path = settings.BASE_DIR / "db" / "schema.sql"
    with open(schema_path, "r", encoding="utf-8") as f:
        schema_sql = f.read()

    with get_db_connection(db_path) as conn:
        conn.executescript(schema_sql)
        conn.commit()


# ==============================================================================
# 🏢 COMPANY & OPPORTUNITY HELPERS (WITH DEDUPLICATION)
# ==============================================================================


def get_or_create_company(
    domain: Optional[str],
    name: str,
    website: Optional[str] = None,
    stage: str = "unknown",
    source: str = "manual",
    description: Optional[str] = None,
    tech_stack: Optional[List[str]] = None,
    funding_info: Optional[str] = None,
    country: Optional[str] = None,
    is_stealth: bool = False,
    db_path: Optional[Path] = None,
) -> int:
    """Get existing company ID by domain/name or insert new one."""
    clean_domain = domain.lower().strip() if domain else None
    clean_name = name.strip()
    tech_json = json.dumps(tech_stack or [])

    with get_db_connection(db_path) as conn:
        cursor = conn.cursor()
        if clean_domain:
            cursor.execute(
                "SELECT id FROM companies WHERE domain = ?", (clean_domain,)
            )
            row = cursor.fetchone()
            if row:
                return row["id"]

        # Search by exact name if domain not provided
        cursor.execute("SELECT id FROM companies WHERE LOWER(name) = LOWER(?)", (clean_name,))
        row = cursor.fetchone()
        if row:
            return row["id"]

        # Insert new company
        cursor.execute(
            """
            INSERT INTO companies (domain, name, website, stage, source, description, tech_stack, funding_info, country, is_stealth)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                clean_domain,
                clean_name,
                website,
                stage,
                source,
                description,
                tech_json,
                funding_info,
                country,
                1 if is_stealth else 0,
            ),
        )
        conn.commit()
        return cursor.lastrowid


def opportunity_exists(url: str, db_path: Optional[Path] = None) -> bool:
    """Check if opportunity URL has already been ingested."""
    if not url:
        return False
    with get_db_connection(db_path) as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT id FROM opportunities WHERE url = ?", (url.strip(),))
        return cursor.fetchone() is not None


def is_company_contacted_recently(
    company_id: int, days: int = 90, db_path: Optional[Path] = None
) -> bool:
    """Check if we already reached out to this company in the last N days."""
    cutoff = (datetime.now() - timedelta(days=days)).isoformat()
    with get_db_connection(db_path) as conn:
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT s.id FROM sent_history s
            JOIN opportunities o ON s.opportunity_id = o.id
            WHERE o.company_id = ? AND s.sent_at >= ?
            """,
            (company_id, cutoff),
        )
        return cursor.fetchone() is not None


def save_opportunity(
    company_id: int,
    type_: str,
    title: str,
    url: str,
    external_id: Optional[str] = None,
    location: Optional[str] = None,
    is_remote: bool = True,
    raw_content: Optional[str] = None,
    status: str = "discovered",
    db_path: Optional[Path] = None,
) -> Optional[int]:
    """Insert opportunity if not duplicate. Returns opportunity ID or None."""
    if opportunity_exists(url, db_path):
        return None

    with get_db_connection(db_path) as conn:
        cursor = conn.cursor()
        cursor.execute(
            """
            INSERT INTO opportunities (company_id, type, title, url, external_id, location, is_remote, raw_content, status)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                company_id,
                type_,
                title.strip(),
                url.strip(),
                external_id,
                location,
                1 if is_remote else 0,
                raw_content,
                status,
            ),
        )
        conn.commit()
        return cursor.lastrowid


def update_opportunity_status(
    opportunity_id: int, status: str, db_path: Optional[Path] = None
) -> None:
    """Update opportunity pipeline status."""
    with get_db_connection(db_path) as conn:
        cursor = conn.cursor()
        cursor.execute(
            "UPDATE opportunities SET status = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
            (status, opportunity_id),
        )
        conn.commit()


# ==============================================================================
# 👥 CONTACTS & ENRICHMENT HELPERS
# ==============================================================================


def save_or_update_contact(
    company_id: int,
    name: str,
    title: Optional[str] = None,
    email: Optional[str] = None,
    email_confidence: str = "missing",
    linkedin_url: Optional[str] = None,
    twitter_url: Optional[str] = None,
    source: str = "enrichment",
    db_path: Optional[Path] = None,
) -> int:
    """Save or update contact details."""
    clean_name = name.strip()
    clean_email = email.lower().strip() if email else None

    with get_db_connection(db_path) as conn:
        cursor = conn.cursor()
        # Look for existing contact at this company by name
        cursor.execute(
            "SELECT id, email, linkedin_url FROM contacts WHERE company_id = ? AND LOWER(name) = LOWER(?)",
            (company_id, clean_name),
        )
        row = cursor.fetchone()
        if row:
            contact_id = row["id"]
            # Update fields if new data provided
            cursor.execute(
                """
                UPDATE contacts
                SET title = COALESCE(?, title),
                    email = COALESCE(?, email),
                    email_confidence = CASE WHEN ? != 'missing' THEN ? ELSE email_confidence END,
                    linkedin_url = COALESCE(?, linkedin_url),
                    twitter_url = COALESCE(?, twitter_url),
                    updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
                """,
                (
                    title,
                    clean_email,
                    email_confidence,
                    email_confidence,
                    linkedin_url,
                    twitter_url,
                    contact_id,
                ),
            )
            conn.commit()
            return contact_id

        # Insert new contact
        cursor.execute(
            """
            INSERT INTO contacts (company_id, name, title, email, email_confidence, linkedin_url, twitter_url, source)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                company_id,
                clean_name,
                title,
                clean_email,
                email_confidence,
                linkedin_url,
                twitter_url,
                source,
            ),
        )
        conn.commit()
        return cursor.lastrowid


def update_contact_email(
    contact_id: int,
    email: str,
    confidence: str = "manual",
    db_path: Optional[Path] = None,
) -> None:
    """Directly update contact email (e.g. from user Telegram input)."""
    with get_db_connection(db_path) as conn:
        cursor = conn.cursor()
        cursor.execute(
            """
            UPDATE contacts
            SET email = ?, email_confidence = ?, updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
            """,
            (email.lower().strip(), confidence, contact_id),
        )
        conn.commit()


# ==============================================================================
# 🧠 EVALUATION & OUTREACH DRAFT HELPERS
# ==============================================================================


def save_evaluation(
    opportunity_id: int,
    fit_score: int,
    decision: str,
    summary_reasoning: str,
    key_synergies: Optional[List[str]] = None,
    potential_risks: Optional[List[str]] = None,
    personalized_hook: Optional[str] = None,
    db_path: Optional[Path] = None,
) -> int:
    """Save or replace opportunity fit evaluation."""
    synergies_json = json.dumps(key_synergies or [])
    risks_json = json.dumps(potential_risks or [])

    with get_db_connection(db_path) as conn:
        cursor = conn.cursor()
        cursor.execute(
            """
            INSERT OR REPLACE INTO evaluations (opportunity_id, fit_score, decision, summary_reasoning, key_synergies, potential_risks, personalized_hook)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                opportunity_id,
                fit_score,
                decision,
                summary_reasoning,
                synergies_json,
                risks_json,
                personalized_hook,
            ),
        )
        conn.commit()
        return cursor.lastrowid


def save_draft(
    opportunity_id: int,
    contact_id: Optional[int],
    subject: str,
    body: str,
    draft_type: str = "initial",
    status: str = "pending",
    db_path: Optional[Path] = None,
) -> int:
    """Save or update outreach email draft."""
    with get_db_connection(db_path) as conn:
        cursor = conn.cursor()
        cursor.execute(
            """
            INSERT INTO outreach_drafts (opportunity_id, contact_id, draft_type, subject, body, status)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (opportunity_id, contact_id, draft_type, subject.strip(), body.strip(), status),
        )
        conn.commit()
        return cursor.lastrowid


def update_draft_body(
    draft_id: int,
    body: str,
    subject: Optional[str] = None,
    status: str = "edited",
    notes: Optional[str] = None,
    db_path: Optional[Path] = None,
) -> None:
    """Update draft content directly (e.g. from user Telegram edit)."""
    with get_db_connection(db_path) as conn:
        cursor = conn.cursor()
        if subject:
            cursor.execute(
                """
                UPDATE outreach_drafts
                SET subject = ?, body = ?, status = ?, revision_notes = ?, updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
                """,
                (subject.strip(), body.strip(), status, notes, draft_id),
            )
        else:
            cursor.execute(
                """
                UPDATE outreach_drafts
                SET body = ?, status = ?, revision_notes = ?, updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
                """,
                (body.strip(), status, notes, draft_id),
            )
        conn.commit()


# ==============================================================================
# 📬 SENT HISTORY & FOLLOW-UP CHECK-IN HELPERS
# ==============================================================================


def record_sent_email(
    opportunity_id: int,
    draft_id: Optional[int],
    contact_id: Optional[int],
    recipient_email: str,
    subject: str,
    body: str,
    notes: Optional[str] = None,
    db_path: Optional[Path] = None,
) -> int:
    """Record successfully sent email in sent_history and update statuses."""
    with get_db_connection(db_path) as conn:
        cursor = conn.cursor()
        cursor.execute(
            """
            INSERT INTO sent_history (opportunity_id, draft_id, contact_id, recipient_email, subject, body, follow_up_status, notes)
            VALUES (?, ?, ?, ?, ?, ?, 'pending_check', ?)
            """,
            (opportunity_id, draft_id, contact_id, recipient_email.strip(), subject.strip(), body.strip(), notes),
        )
        sent_id = cursor.lastrowid

        # Update opportunity and draft status to 'sent'
        cursor.execute(
            "UPDATE opportunities SET status = 'sent', updated_at = CURRENT_TIMESTAMP WHERE id = ?",
            (opportunity_id,),
        )
        if draft_id:
            cursor.execute(
                "UPDATE outreach_drafts SET status = 'sent', updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                (draft_id,),
            )

        conn.commit()
        return sent_id


def get_pending_follow_ups(
    min_days: int = 5, max_days: int = 14, db_path: Optional[Path] = None
) -> List[Dict[str, Any]]:
    """Fetch sent emails ready for follow-up check-in (sent between min_days and max_days ago)."""
    now = datetime.now()
    cutoff_recent = (now - timedelta(days=min_days)).isoformat()
    cutoff_old = (now - timedelta(days=max_days)).isoformat()

    with get_db_connection(db_path) as conn:
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT s.*, c.name as company_name, c.domain as company_domain,
                   ct.name as contact_name, ct.title as contact_title, ct.linkedin_url
            FROM sent_history s
            JOIN opportunities o ON s.opportunity_id = o.id
            JOIN companies c ON o.company_id = c.id
            LEFT JOIN contacts ct ON s.contact_id = ct.id
            WHERE s.follow_up_status = 'pending_check'
              AND s.sent_at <= ?
              AND s.sent_at >= ?
              AND (s.last_follow_up_check IS NULL OR s.last_follow_up_check <= ?)
            ORDER BY s.sent_at ASC
            """,
            (cutoff_recent, cutoff_old, (now - timedelta(days=2)).isoformat()),
        )
        rows = cursor.fetchall()
        return [dict(row) for row in rows]


def update_follow_up_status(
    sent_id: int, status: str, notes: Optional[str] = None, db_path: Optional[Path] = None
) -> None:
    """Update follow-up status (e.g. 'replied', 'bump_sent', 'closed')."""
    with get_db_connection(db_path) as conn:
        cursor = conn.cursor()
        cursor.execute(
            """
            UPDATE sent_history
            SET follow_up_status = ?, notes = COALESCE(?, notes), last_follow_up_check = CURRENT_TIMESTAMP
            WHERE id = ?
            """,
            (status, notes, sent_id),
        )
        conn.commit()


# ==============================================================================
# 📊 AUDIT LOG & METRICS
# ==============================================================================


def log_audit(
    event_type: str, message: str, payload: Optional[Dict[str, Any]] = None, db_path: Optional[Path] = None
) -> None:
    """Write an entry into audit_log."""
    payload_json = json.dumps(payload) if payload else None
    with get_db_connection(db_path) as conn:
        cursor = conn.cursor()
        cursor.execute(
            "INSERT INTO audit_log (event_type, message, payload) VALUES (?, ?, ?)",
            (event_type, message, payload_json),
        )
        conn.commit()


def get_system_stats(db_path: Optional[Path] = None) -> Dict[str, int]:
    """Get aggregated pipeline statistics."""
    with get_db_connection(db_path) as conn:
        cursor = conn.cursor()
        stats = {}
        for status in ["discovered", "evaluated", "filtered", "pending_approval", "approved", "rejected", "sent"]:
            cursor.execute("SELECT COUNT(*) FROM opportunities WHERE status = ?", (status,))
            stats[f"opportunities_{status}"] = cursor.fetchone()[0]

        cursor.execute("SELECT COUNT(*) FROM companies")
        stats["total_companies"] = cursor.fetchone()[0]

        cursor.execute("SELECT COUNT(*) FROM contacts")
        stats["total_contacts"] = cursor.fetchone()[0]

        cursor.execute("SELECT COUNT(*) FROM sent_history")
        stats["total_sent"] = cursor.fetchone()[0]

        cursor.execute("SELECT COUNT(*) FROM sent_history WHERE follow_up_status = 'replied'")
        stats["total_replies"] = cursor.fetchone()[0]

        return stats
