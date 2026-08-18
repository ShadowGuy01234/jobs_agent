"""SQLite automated database backup utility."""

import logging
import shutil
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Optional

from config import settings
from db.database import log_audit

logger = logging.getLogger(__name__)


def create_database_backup(
    db_path: Optional[Path] = None, backup_dir: Optional[Path] = None
) -> Optional[Path]:
    """Create a safe, atomic snapshot backup of the SQLite database."""
    source_path = db_path or settings.DATABASE_PATH
    target_dir = backup_dir or settings.BACKUP_DIR
    target_dir.mkdir(parents=True, exist_ok=True)

    if not source_path.exists():
        logger.warning(f"Database file not found at {source_path}. Skipping backup.")
        return None

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_file = target_dir / f"outreach_backup_{timestamp}.db"

    try:
        # Use SQLite Online Backup API for safe snapshot during active writes
        src_conn = sqlite3.connect(str(source_path))
        dst_conn = sqlite3.connect(str(backup_file))
        with dst_conn:
            src_conn.backup(dst_conn)
        dst_conn.close()
        src_conn.close()

        logger.info(f"Database backup successfully created: {backup_file}")
        log_audit(
            event_type="backup",
            message=f"Database backup created: {backup_file.name}",
            payload={"backup_file": str(backup_file)},
        )
        return backup_file
    except Exception as e:
        logger.error(f"Failed to create database backup: {e}", exc_info=True)
        return None
