"""Background task scheduler using APScheduler."""

import asyncio
import logging
from typing import Any, Optional
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger

from backup import create_database_backup
from bot.card_renderer import render_follow_up_card, render_opportunity_card
from config import settings
from db.database import get_pending_follow_ups, log_audit
from discovery.manager import DiscoveryManager
from heartbeat import run_anti_idle_pulse
from pipeline.orchestrator import PipelineOrchestrator

logger = logging.getLogger(__name__)


class OutreachScheduler:
    """Manages periodic discovery sweeps, 5-day follow-up checks, anti-idle pulses, and DB backups."""

    def __init__(self, bot_app: Optional[Any] = None):
        self.scheduler = AsyncIOScheduler()
        self.discovery_manager = DiscoveryManager()
        self.orchestrator = PipelineOrchestrator()
        self.bot_app = bot_app

    async def run_scheduled_discovery(self) -> None:
        """Periodic discovery scan job."""
        logger.info("Executing scheduled discovery scan...")
        try:
            new_ids = await self.discovery_manager.run_discovery_sweep(limit_per_source=10)
            logger.info(f"Scheduled discovery completed: {len(new_ids)} new opportunities ingested.")

            # Process top opportunities
            alerts_sent = 0
            for opp_id in new_ids:
                if alerts_sent >= settings.MAX_ALERTS_PER_DAY:
                    break

                interrupt_payload = await self.orchestrator.process_opportunity(opp_id)
                if interrupt_payload and interrupt_payload.get("fit_score", 0) >= settings.MIN_FIT_SCORE:
                    if self.bot_app and settings.TELEGRAM_CHAT_ID:
                        text, keyboard = render_opportunity_card(interrupt_payload)
                        await self.bot_app.bot.send_message(
                            chat_id=settings.TELEGRAM_CHAT_ID,
                            text=text,
                            reply_markup=keyboard,
                            parse_mode="HTML",
                        )
                        alerts_sent += 1

        except Exception as e:
            logger.error(f"Error during scheduled discovery: {e}", exc_info=True)

    async def run_follow_up_check(self) -> None:
        """Daily scan for emails sent 5-7 days ago needing Telegram check-ins."""
        logger.info("Executing daily follow-up check...")
        try:
            pending_items = get_pending_follow_ups(min_days=5, max_days=14)
            logger.info(f"Found {len(pending_items)} sent emails awaiting follow-up review.")

            if self.bot_app and settings.TELEGRAM_CHAT_ID:
                for item in pending_items[:5]:  # Send max 5 check-ins at a time to avoid spam
                    text, keyboard = render_follow_up_card(item)
                    await self.bot_app.bot.send_message(
                        chat_id=settings.TELEGRAM_CHAT_ID,
                        text=text,
                        reply_markup=keyboard,
                        parse_mode="HTML",
                    )
        except Exception as e:
            logger.error(f"Error during follow-up check: {e}", exc_info=True)

    def run_anti_idle_heartbeat_sync(self) -> None:
        """Trigger synchronous anti-idle pulse in worker thread."""
        run_anti_idle_pulse(duration_seconds=30)

    def start(self) -> None:
        """Start the scheduler with all configured triggers."""
        # 1. Periodic Discovery Scan (Runs every 6 hours)
        self.scheduler.add_job(
            self.run_scheduled_discovery,
            trigger=IntervalTrigger(hours=6),
            id="discovery_job",
            replace_existing=True,
        )

        # 2. Daily Follow-Up Check (Runs every morning at 09:30 AM)
        self.scheduler.add_job(
            self.run_follow_up_check,
            trigger=CronTrigger(hour=9, minute=30),
            id="follow_up_job",
            replace_existing=True,
        )

        # 3. Oracle Cloud Anti-Idle Heartbeat (Runs every N hours)
        if settings.ORACLE_HEARTBEAT_ENABLED:
            self.scheduler.add_job(
                self.run_anti_idle_heartbeat_sync,
                trigger=IntervalTrigger(hours=settings.HEARTBEAT_INTERVAL_HOURS),
                id="oracle_heartbeat_job",
                replace_existing=True,
            )

        # 4. Daily Database Backup (Runs at 03:00 AM)
        self.scheduler.add_job(
            create_database_backup,
            trigger=CronTrigger(hour=3, minute=0),
            id="backup_job",
            replace_existing=True,
        )

        self.scheduler.start()
        logger.info("Outreach background scheduler successfully started.")

    def shutdown(self) -> None:
        """Stop scheduler cleanly."""
        if self.scheduler.running:
            self.scheduler.shutdown()
            logger.info("Outreach background scheduler stopped.")
