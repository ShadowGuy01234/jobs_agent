"""Unit tests for Phase 6: Scheduler, Heartbeat, Backups & API."""

import gc
import tempfile
from pathlib import Path
from fastapi.testclient import TestClient
import pytest

from app import app
from backup import create_database_backup
from db.database import init_db
from heartbeat import run_anti_idle_pulse
from scheduler import OutreachScheduler


@pytest.fixture
def temp_db():
    """Create a fresh temporary SQLite database."""
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db_path = Path(f.name)
    init_db(db_path)
    yield db_path
    gc.collect()
    try:
        if db_path.exists():
            db_path.unlink()
        wal = db_path.with_suffix(".db-wal")
        shm = db_path.with_suffix(".db-shm")
        if wal.exists():
            wal.unlink()
        if shm.exists():
            shm.unlink()
    except (PermissionError, OSError):
        pass


def test_anti_idle_pulse():
    """Test Oracle anti-idle pulse computation."""
    run_anti_idle_pulse(duration_seconds=1)
    assert True


def test_database_backup(temp_db):
    """Test SQLite snapshot backup creation."""
    with tempfile.TemporaryDirectory() as backup_dir:
        backup_file = create_database_backup(db_path=temp_db, backup_dir=Path(backup_dir))
        assert backup_file is not None
        assert backup_file.exists()
        assert backup_file.stat().st_size > 0


@pytest.mark.asyncio
async def test_scheduler_jobs():
    """Test scheduler registers all 4 scheduled jobs."""
    scheduler = OutreachScheduler()
    scheduler.start()
    job_ids = [j.id for j in scheduler.scheduler.get_jobs()]
    assert "discovery_job" in job_ids
    assert "follow_up_job" in job_ids
    assert "oracle_heartbeat_job" in job_ids
    assert "backup_job" in job_ids
    scheduler.shutdown()


def test_fastapi_health_endpoints():
    """Test FastAPI /health and /status endpoints."""
    with TestClient(app) as client:
        resp = client.get("/health")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "ok"

        status_resp = client.get("/status")
        assert status_resp.status_code == 200
        status_data = status_resp.json()
        assert status_data["status"] == "running"
        assert "metrics" in status_data


def test_clear_reviews_and_backlog(temp_db):
    """Test clearing pending reviews and unexplored backlog opportunities."""
    from db.database import (
        clear_all_pending_and_unexplored,
        clear_pending_reviews,
        clear_unexplored_backlog,
        get_or_create_company,
        get_opportunity_card_payload,
        save_draft,
        save_opportunity,
        update_opportunity_status,
    )

    company_id = get_or_create_company(
        domain="testai.io", name="TestAI", db_path=temp_db
    )
    opp1 = save_opportunity(
        company_id=company_id,
        type_="founder_reachout",
        title="Test Match 1",
        url="https://testai.io/job/1",
        db_path=temp_db,
    )
    opp2 = save_opportunity(
        company_id=company_id,
        type_="founder_reachout",
        title="Test Match 2",
        url="https://testai.io/job/2",
        db_path=temp_db,
    )
    save_draft(opp1, None, subject="Quick note", body="Draft text", db_path=temp_db)
    update_opportunity_status(opp1, "pending_approval", db_path=temp_db)

    # Verify payload fetch
    payload = get_opportunity_card_payload(opp1, db_path=temp_db)
    assert payload is not None
    assert payload["company_name"] == "TestAI"
    assert payload["draft_subject"] == "Quick note"

    # Test clear pending reviews
    cleared_pending = clear_pending_reviews(db_path=temp_db)
    assert cleared_pending == 1

    # Test clear backlog
    cleared_backlog = clear_unexplored_backlog(db_path=temp_db)
    assert cleared_backlog == 1

    # Test clear all
    opp3 = save_opportunity(
        company_id=company_id,
        type_="founder_reachout",
        title="Test Match 3",
        url="https://testai.io/job/3",
        db_path=temp_db,
    )
    update_opportunity_status(opp3, "pending_approval", db_path=temp_db)
    p_cnt, b_cnt = clear_all_pending_and_unexplored(db_path=temp_db)
    assert p_cnt == 1
    assert b_cnt == 0


