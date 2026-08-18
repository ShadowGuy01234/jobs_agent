"""Oracle Cloud Always Free Tier anti-idle heartbeat pulse generator."""

import hashlib
import logging
import math
import time
from typing import Optional

from config import settings
from db.database import log_audit

logger = logging.getLogger(__name__)


def run_anti_idle_pulse(duration_seconds: int = 30) -> None:
    """Execute a controlled 30-second CPU/RAM pulse to maintain Oracle VM active status.

    Oracle Free Tier reclamation policy stops instances with <20% average CPU/RAM over 7 days.
    This pulse uses a controlled mathematical matrix calculation on 1 core for 30s.
    """
    if not settings.ORACLE_HEARTBEAT_ENABLED:
        logger.debug("Oracle anti-idle heartbeat is disabled.")
        return

    logger.info(f"Starting Oracle anti-idle heartbeat pulse ({duration_seconds}s)...")
    start_time = time.time()
    iterations = 0

    # Allocate a small working buffer (~20MB)
    buffer = [math.sin(i) * math.cos(i) for i in range(50000)]

    while (time.time() - start_time) < duration_seconds:
        # Perform light cryptographic & mathematical work
        chunk = hashlib.sha256(f"pulse_{iterations}_{time.time()}".encode()).hexdigest()
        for i in range(len(buffer)):
            buffer[i] = math.sqrt(abs(buffer[i] + math.sin(iterations)))
        iterations += 1
        time.sleep(0.01)  # Yield CPU briefly to prevent locking

    del buffer
    elapsed = round(time.time() - start_time, 2)
    logger.info(f"Oracle anti-idle heartbeat pulse completed ({elapsed}s, {iterations} cycles).")

    log_audit(
        event_type="heartbeat",
        message=f"Oracle anti-idle heartbeat pulse completed in {elapsed}s",
        payload={"iterations": iterations, "duration_seconds": elapsed},
    )
