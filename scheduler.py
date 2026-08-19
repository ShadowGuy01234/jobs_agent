"""Background task scheduler using APScheduler.

Features:
- Hourly 2-source rotating discovery sweep with automated Telegram progress reports.
- Daily 09:30 AM follow-up bump check for sent emails awaiting replies.
- Oracle Cloud / VPS anti-idle heartbeat pulse.
- Automated daily SQLite database backups.
"""

import asyncio
import html
import logging
from datetime import datetime
from typing import Any, List, Optional
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger

from backup import create_database_backup
from bot.card_renderer import render_follow_up_card, render_opportunity_card
from config import settings
from db.database import (
    get_opportunity_evaluation_summary,
    get_pending_follow_ups,
    get_unscored_opportunity_ids,
)
from discovery.manager import DiscoveryManager
from heartbeat import run_anti_idle_pulse
from pipeline.orchestrator import PipelineOrchestrator

logger = logging.getLogger(__name__)

# Complete list of 11 discovery connectors to rotate through
ROTATING_SOURCES: List[str] = [
    "yc",
    "hackernews",
    "india",
    "producthunt",
    "tavily",
    "ashby",
    "greenhouse",
    "lever",
    "vc_stealth",
    "sec_edgar",
    "watchlist",
]


class OutreachScheduler:
    """Manages hourly rotating discovery sweeps, follow-up checks, anti-idle pulses, and DB backups."""

    def __init__(self, bot_app: Optional[Any] = None):
        self.scheduler = AsyncIOScheduler()
        self.discovery_manager = DiscoveryManager()
        self.orchestrator = PipelineOrchestrator()
        self.bot_app = bot_app
        self.current_source_index = 0

    async def run_scheduled_discovery(self) -> None:
        """Hourly rotating discovery sweep (2 sources per hour) with Telegram report."""
        total_sources = len(ROTATING_SOURCES)
        s1 = ROTATING_SOURCES[self.current_source_index % total_sources]
        s2 = ROTATING_SOURCES[(self.current_source_index + 1) % total_sources]
        sources_to_run = [s1, s2]

        # Advance index for the next hour
        self.current_source_index = (self.current_source_index + 2) % total_sources
        next_s1 = ROTATING_SOURCES[self.current_source_index % total_sources]
        next_s2 = ROTATING_SOURCES[(self.current_source_index + 1) % total_sources]

        current_time_str = datetime.now().strftime("%I:%M %p")
        logger.info(f"Executing hourly discovery sweep for sources: {sources_to_run} at {current_time_str}...")

        try:
            # 1. Ingest new opportunities from the 2 scheduled sources
            new_ids = await self.discovery_manager.run_discovery_sweep(
                sources=sources_to_run, limit_per_source=5
            )
            logger.info(
                f"Hourly discovery ({', '.join(sources_to_run)}): {len(new_ids)} new opportunities ingested."
            )

            # 2. Select IDs to evaluate (new IDs + unscored backlog up to batch limit)
            limit_to_process = new_ids[: settings.MAX_ALERTS_PER_DAY]
            if not limit_to_process:
                backlog_ids = get_unscored_opportunity_ids(limit=5)
                if backlog_ids:
                    limit_to_process = backlog_ids

            alerts_sent = 0
            evaluated_count = len(limit_to_process)
            high_fit_companies: List[str] = []

            # 3. Process opportunities through LangGraph pipeline
            for i, opp_id in enumerate(limit_to_process):
                try:
                    if i > 0:
                        await asyncio.sleep(1.5)  # Built-in pacing

                    interrupt_payload = await self.orchestrator.process_opportunity(opp_id)
                    fit_score = interrupt_payload.get("fit_score", 0) if interrupt_payload else 0

                    if interrupt_payload and fit_score >= settings.MIN_FIT_SCORE:
                        company_name = interrupt_payload.get("company_name", "Opportunity")
                        high_fit_companies.append(f"<b>{html.escape(company_name)}</b> ({fit_score}/100)")
                        alerts_sent += 1

                        if self.bot_app and settings.TELEGRAM_CHAT_ID:
                            text, keyboard = render_opportunity_card(interrupt_payload)
                            await self.bot_app.bot.send_message(
                                chat_id=settings.TELEGRAM_CHAT_ID,
                                text=text,
                                reply_markup=keyboard,
                                parse_mode="HTML",
                            )
                except Exception as e:
                    logger.error(f"Error processing opp #{opp_id} during hourly sweep: {e}", exc_info=True)

            # 4. Send hourly report back to Telegram
            if self.bot_app and settings.TELEGRAM_CHAT_ID:
                matches_str = (
                    f"• <b>🎯 High-Fit Matches Sent ({alerts_sent}):</b>\n  " + "\n  ".join(high_fit_companies)
                    if high_fit_companies
                    else "• <b>🎯 High-Fit Matches Sent:</b> 0 (Threshold: 70/100)"
                )

                hourly_report_msg = (
                    f"⏰ <b>Hourly Discovery Sweep Report ({current_time_str})</b>\n\n"
                    f"• <b>Scanned Sources:</b> <code>{s1}</code>, <code>{s2}</code>\n"
                    f"• <b>New Ingested:</b> {len(new_ids)}\n"
                    f"• <b>Evaluated Leads:</b> {evaluated_count}\n"
                    f"{matches_str}\n"
                    f"• <b>Filtered / Out of Scope:</b> {max(0, evaluated_count - alerts_sent)}\n"
                    f"──────────────────────────\n"
                    f"<i>⏭ Next Hourly Sweep (in 1 hr): <code>{next_s1}</code>, <code>{next_s2}</code></i>"
                )

                await self.bot_app.bot.send_message(
                    chat_id=settings.TELEGRAM_CHAT_ID,
                    text=hourly_report_msg,
                    parse_mode="HTML",
                )

        except Exception as e:
            logger.error(f"Error during hourly rotating discovery: {e}", exc_info=True)
            if self.bot_app and settings.TELEGRAM_CHAT_ID:
                try:
                    await self.bot_app.bot.send_message(
                        chat_id=settings.TELEGRAM_CHAT_ID,
                        text=f"⚠️ <b>Hourly Discovery Notice:</b> Error scanning <code>{s1}</code>, <code>{s2}</code>: {html.escape(str(e))}",
                        parse_mode="HTML",
                    )
                except Exception:
                    pass

    async def run_follow_up_check(self) -> None:
        """Daily scan for emails sent 5-7 days ago needing Telegram check-ins."""
        logger.info("Executing daily follow-up check...")
        try:
            pending_items = get_pending_follow_ups(min_days=5, max_days=14)
            logger.info(f"Found {len(pending_items)} sent emails awaiting follow-up review.")

            if self.bot_app and settings.TELEGRAM_CHAT_ID and pending_items:
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
        # 1. Hourly Rotating Discovery Sweep (Runs every 1 hour, cycling through 2 sources at a time)
        self.scheduler.add_job(
            self.run_scheduled_discovery,
            trigger=IntervalTrigger(hours=1),
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
        logger.info("Outreach background scheduler successfully started (1-Hour 2-Source Rotation).")

    def shutdown(self) -> None:
        """Stop scheduler cleanly."""
        if self.scheduler.running:
            self.scheduler.shutdown()
            logger.info("Outreach background scheduler stopped.")
