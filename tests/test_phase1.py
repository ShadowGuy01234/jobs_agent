"""Unit tests for Phase 1: DB Schema, Deduplication, Profile & Resume Parsing."""

import tempfile
from pathlib import Path
import pytest

from db.database import (
    init_db,
    get_or_create_company,
    save_opportunity,
    opportunity_exists,
    is_company_contacted_recently,
    save_or_update_contact,
    update_contact_email,
    save_evaluation,
    save_draft,
    update_draft_body,
    record_sent_email,
    get_pending_follow_ups,
    update_follow_up_status,
    get_system_stats,
)
from profile.parser import load_user_profile, load_resume_text


@pytest.fixture
def temp_db():
    """Create a fresh temporary SQLite database."""
    import gc
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db_path = Path(f.name)
    init_db(db_path)
    yield db_path
    gc.collect()
    try:
        if db_path.exists():
            db_path.unlink()
        # Also clean up WAL and SHM files if present
        wal = db_path.with_suffix(".db-wal")
        shm = db_path.with_suffix(".db-shm")
        if wal.exists():
            wal.unlink()
        if shm.exists():
            shm.unlink()
    except (PermissionError, OSError):
        pass


def test_company_deduplication(temp_db):
    """Test company creation and domain deduplication."""
    c1_id = get_or_create_company(
        domain="codemorph.dev",
        name="CodeMorph AI",
        website="https://codemorph.dev",
        stage="seed",
        source="yc",
        tech_stack=["Python", "Rust"],
        db_path=temp_db,
    )
    assert c1_id > 0

    # Inserting same domain should return existing ID
    c2_id = get_or_create_company(
        domain="codemorph.dev",
        name="CodeMorph Inc",
        db_path=temp_db,
    )
    assert c1_id == c2_id


def test_opportunity_deduplication(temp_db):
    """Test opportunity insertion and URL deduplication."""
    c_id = get_or_create_company(
        domain="tavily.com",
        name="Tavily",
        db_path=temp_db,
    )
    url = "https://tavily.com/jobs/backend-lead"
    opp_id = save_opportunity(
        company_id=c_id,
        type_="job_posting",
        title="Senior Backend Lead",
        url=url,
        db_path=temp_db,
    )
    assert opp_id is not None
    assert opportunity_exists(url, temp_db) is True

    # Duplicate URL insertion should return None
    dup_id = save_opportunity(
        company_id=c_id,
        type_="job_posting",
        title="Duplicate Post",
        url=url,
        db_path=temp_db,
    )
    assert dup_id is None


def test_contact_and_draft_flow(temp_db):
    """Test contact creation, manual email update, and draft editing."""
    c_id = get_or_create_company(domain="agentic.ai", name="Agentic AI", db_path=temp_db)
    opp_id = save_opportunity(
        company_id=c_id,
        type_="founder_reachout",
        title="Agentic AI YC W25",
        url="https://agentic.ai/launch",
        db_path=temp_db,
    )

    # Save contact with missing email
    contact_id = save_or_update_contact(
        company_id=c_id,
        name="Alex Smith",
        title="Founder & CEO",
        linkedin_url="https://linkedin.com/in/alexsmith",
        db_path=temp_db,
    )
    assert contact_id > 0

    # User manually provides email
    update_contact_email(contact_id, "alex@agentic.ai", confidence="manual", db_path=temp_db)

    # Save evaluation
    eval_id = save_evaluation(
        opportunity_id=opp_id,
        fit_score=92,
        decision="PROCEED",
        summary_reasoning="Strong match on AI agent workflows",
        key_synergies=["Python", "LangGraph"],
        db_path=temp_db,
    )
    assert eval_id > 0

    # Save and edit draft
    draft_id = save_draft(
        opportunity_id=opp_id,
        contact_id=contact_id,
        subject="Building Agentic AI / YC W25",
        body="Original draft body",
        db_path=temp_db,
    )
    assert draft_id > 0

    update_draft_body(draft_id, body="Updated draft text from Telegram", status="edited", db_path=temp_db)

    # Record sent email
    sent_id = record_sent_email(
        opportunity_id=opp_id,
        draft_id=draft_id,
        contact_id=contact_id,
        recipient_email="alex@agentic.ai",
        subject="Building Agentic AI / YC W25",
        body="Updated draft text from Telegram",
        db_path=temp_db,
    )
    assert sent_id > 0
    assert is_company_contacted_recently(c_id, days=90, db_path=temp_db) is True

    # Check stats
    stats = get_system_stats(temp_db)
    assert stats["total_companies"] == 1
    assert stats["total_sent"] == 1


def test_profile_and_resume_loading():
    """Test loading user_profile.yaml and parsing resume."""
    profile = load_user_profile()
    assert profile.candidate.full_name.strip()
    assert "pre_seed" in profile.targeting.target_stages
    assert "series_c" in profile.targeting.target_stages
    assert profile.targeting.location.remote_only is True
    assert "India" in profile.targeting.location.prioritized_regions
    assert len(profile.candidate.core_skills) > 0

    resume_text = load_resume_text()
    assert resume_text is not None
    assert len(resume_text.strip()) > 0


def test_app_settings_contact_cache_and_backlog_priority(temp_db, monkeypatch):
    """Test persisted app_settings, verified contact reuse, and backlog prioritization."""
    from config import settings
    from db.database import (
        apply_persisted_settings,
        get_app_setting,
        get_unscored_opportunity_ids,
        get_verified_company_contact,
        set_app_setting,
    )

    orig_dry = settings.DRY_RUN
    orig_score = settings.MIN_FIT_SCORE
    try:
        set_app_setting("dry_run", "false", db_path=temp_db)
        set_app_setting("min_fit_score", "82", db_path=temp_db)
        assert get_app_setting("dry_run", db_path=temp_db) == "false"
        apply_persisted_settings(db_path=temp_db)
        assert settings.DRY_RUN is False
        assert settings.MIN_FIT_SCORE == 82
    finally:
        settings.DRY_RUN = orig_dry
        settings.MIN_FIT_SCORE = orig_score

    c_sec = get_or_create_company(domain=None, name="Holding LLC", source="sec_edgar", db_path=temp_db)
    c_hd = get_or_create_company(domain="acme.ai", name="Acme AI", source="hunter_discover", db_path=temp_db)
    opp_sec = save_opportunity(c_sec, "stealth_reachout", "Holding LLC Form D", "https://sec.gov/1", db_path=temp_db)
    opp_hd = save_opportunity(c_hd, "founder_reachout", "Acme AI", "https://acme.ai", db_path=temp_db)
    opp_job = save_opportunity(c_hd, "job_posting", "AI Engineer", "https://acme.ai/jobs/1", db_path=temp_db)

    ordered = get_unscored_opportunity_ids(limit=10, db_path=temp_db)
    assert ordered[0] == opp_job
    assert ordered[1] == opp_hd
    assert ordered[-1] == opp_sec

    # Unverified contact should not be returned as cached verified contact
    save_or_update_contact(c_hd, "Alex", email="alex@acme.ai", email_confidence="low_confidence", db_path=temp_db)
    assert get_verified_company_contact(c_hd, db_path=temp_db) is None

    # Verified contact is reusable across repeat postings
    save_or_update_contact(c_hd, "Alex", email="alex@acme.ai", email_confidence="verified", db_path=temp_db)
    cached = get_verified_company_contact(c_hd, db_path=temp_db)
    assert cached is not None
    assert cached["email"] == "alex@acme.ai"
