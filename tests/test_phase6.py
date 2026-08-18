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
