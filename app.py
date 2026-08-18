"""Main FastAPI Application & Orchestration Runner."""

import asyncio
import logging
from contextlib import asynccontextmanager
from typing import Optional
from fastapi import BackgroundTasks, FastAPI
from fastapi.responses import JSONResponse
import uvicorn

from backup import create_database_backup
from bot.telegram_bot import TelegramBotController
from config import settings
from db.database import get_system_stats, init_db
from discovery.manager import DiscoveryManager
from heartbeat import run_anti_idle_pulse
from scheduler import OutreachScheduler

import logging
from logging.handlers import RotatingFileHandler

# Ensure logs directory exists
settings.LOGS_DIR.mkdir(parents=True, exist_ok=True)

# Configure logging with both Console and Rotating File Handlers
log_formatter = logging.Formatter("%(asctime)s [%(levelname)s] %(name)s: %(message)s")

file_handler = RotatingFileHandler(
    settings.LOG_FILE_PATH,
    maxBytes=5 * 1024 * 1024,  # 5 MB
    backupCount=5,
    encoding="utf-8",
)
file_handler.setFormatter(log_formatter)
file_handler.setLevel(logging.INFO)

console_handler = logging.StreamHandler()
console_handler.setFormatter(log_formatter)
console_handler.setLevel(logging.INFO)

root_logger = logging.getLogger()
root_logger.setLevel(logging.INFO)
root_logger.addHandler(file_handler)
root_logger.addHandler(console_handler)

logger = logging.getLogger("app")

bot_controller: Optional[TelegramBotController] = None
scheduler_instance: Optional[OutreachScheduler] = None
telegram_app = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Lifespan context manager: initializes DB, Telegram bot polling, and background schedulers."""
    global bot_controller, scheduler_instance, telegram_app
    logger.info("Initializing SQLite database...")
    init_db()

    # Initialize Telegram Bot (if token configured)
    if settings.TELEGRAM_BOT_TOKEN:
        logger.info("Initializing Telegram Bot Controller...")
        bot_controller = TelegramBotController()
        telegram_app = bot_controller.build_application()
        await telegram_app.initialize()
        await telegram_app.start()
        await telegram_app.updater.start_polling()
        logger.info("Telegram Bot long-polling started.")
    else:
        logger.warning("TELEGRAM_BOT_TOKEN not configured. Running in headless mode.")

    # Start APScheduler
    logger.info("Starting background scheduler...")
    scheduler_instance = OutreachScheduler(bot_app=telegram_app)
    scheduler_instance.start()

    yield

    # Teardown
    logger.info("Shutting down services...")
    if scheduler_instance:
        scheduler_instance.shutdown()
    if telegram_app:
        await telegram_app.updater.stop()
        await telegram_app.stop()
        await telegram_app.shutdown()
    logger.info("All services shut down cleanly.")


app = FastAPI(
    title="Personal AI Job & Startup Outreach System",
    version="0.1.0",
    description="Autonomous dual-track discovery, candidate fit evaluation, and Telegram human-in-the-loop outreach.",
    lifespan=lifespan,
)


@app.get("/health")
async def health():
    """Health check endpoint."""
    return {"status": "ok", "dry_run": settings.DRY_RUN, "heartbeat_enabled": settings.ORACLE_HEARTBEAT_ENABLED}


@app.get("/status")
async def status():
    """Pipeline and database statistics."""
    stats = get_system_stats()
    return JSONResponse(content={"status": "running", "metrics": stats, "dry_run": settings.DRY_RUN})


@app.post("/trigger/discovery")
async def trigger_discovery(background_tasks: BackgroundTasks, source: Optional[str] = None):
    """Manually trigger discovery sweep via API."""
    if scheduler_instance:
        background_tasks.add_task(scheduler_instance.run_scheduled_discovery)
        return {"status": "discovery_triggered", "source": source or "all"}
    return {"status": "scheduler_not_running"}


@app.post("/trigger/followup")
async def trigger_followup(background_tasks: BackgroundTasks):
    """Manually trigger 5-day follow-up check-in scanner."""
    if scheduler_instance:
        background_tasks.add_task(scheduler_instance.run_follow_up_check)
        return {"status": "followup_check_triggered"}
    return {"status": "scheduler_not_running"}


@app.post("/trigger/heartbeat")
async def trigger_heartbeat(background_tasks: BackgroundTasks):
    """Manually trigger Oracle anti-idle compute pulse."""
    background_tasks.add_task(run_anti_idle_pulse, 15)
    return {"status": "heartbeat_triggered", "duration": 15}


@app.post("/trigger/backup")
async def trigger_backup():
    """Manually trigger database snapshot backup."""
    backup_file = create_database_backup()
    return {"status": "backup_created", "file": str(backup_file)}


def start():
    """Application entrypoint."""
    uvicorn.run("app:app", host=settings.HOST, port=settings.PORT, reload=False)


if __name__ == "__main__":
    start()
