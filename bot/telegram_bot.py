"""Interactive Telegram Bot Controller using Long-Polling and Inline Keyboards."""

import asyncio
import html
import logging
import re
from typing import Any, Dict, Optional
from telegram import Update
from telegram.constants import ParseMode
from telegram.ext import (
    Application,
    ApplicationBuilder,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

from bot.card_renderer import render_follow_up_card, render_opportunity_card
from config import settings
from db.database import (
    get_db_connection,
    get_pattern_used_for_contact,
    get_system_stats,
    log_audit,
    record_pattern_success,
    update_contact_email,
    update_draft_body,
    update_follow_up_status,
    update_opportunity_status,
)
from discovery.manager import DiscoveryManager
from pipeline.orchestrator import PipelineOrchestrator
from profile.parser import load_user_profile

logger = logging.getLogger(__name__)


class TelegramBotController:
    """Telegram Bot Controller running in long-polling mode (zero inbound ports required)."""

    def __init__(self, token: Optional[str] = None, authorized_chat_id: Optional[str] = None):
        self.token = token or settings.TELEGRAM_BOT_TOKEN
        self.authorized_chat_id = str(authorized_chat_id or settings.TELEGRAM_CHAT_ID).strip()
        self.orchestrator = PipelineOrchestrator()
        self.discovery_manager = DiscoveryManager()
        self.user_sessions: Dict[str, Dict[str, Any]] = {}
        self.app: Optional[Application] = None

    def is_authorized(self, update: Update) -> bool:
        """Verify that incoming message/callback is from the authorized user chat or username."""
        if not update.effective_chat:
            return False
        chat_id = str(update.effective_chat.id).strip()
        username = (update.effective_user.username or "").strip().lstrip("@").lower() if update.effective_user else ""
        auth_target = self.authorized_chat_id.lstrip("@").lower()

        if not auth_target:
            # If not configured, auto-authorize and capture chat_id
            settings.TELEGRAM_CHAT_ID = chat_id
            return True

        # Check numeric ID match or username handle match
        if chat_id == self.authorized_chat_id or (username and username == auth_target):
            # Auto-save numeric chat ID for proactive scheduler broadcasts
            if settings.TELEGRAM_CHAT_ID != chat_id:
                settings.TELEGRAM_CHAT_ID = chat_id
                logger.info(f"Authorized user confirmed: username=@{username}, numeric chat_id={chat_id}")
            return True

        logger.warning(f"Unauthorized message received from chat_id={chat_id}, username=@{username}")
        return False

    # ==========================================================================
    # 📱 COMMAND HANDLERS
    # ==========================================================================

    async def _send_opportunity_card(
        self, chat_id: int, payload: Dict[str, Any], context: ContextTypes.DEFAULT_TYPE
    ) -> None:
        """Safely send an opportunity card to Telegram with HTML fallback."""
        text, keyboard = render_opportunity_card(payload)
        try:
            await context.bot.send_message(
                chat_id=chat_id,
                text=text,
                reply_markup=keyboard,
                parse_mode=ParseMode.HTML,
                disable_web_page_preview=True,
            )
        except Exception as e:
            logger.warning(f"HTML render failed: {e}. Falling back to plain text format.")
            clean_text = re.sub(r"<[^>]+>", "", text)
            await context.bot.send_message(
                chat_id=chat_id,
                text=clean_text,
                reply_markup=keyboard,
                disable_web_page_preview=True,
            )

    async def cmd_start(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Handle /start and /help commands."""
        if not self.is_authorized(update):
            return

        user_chat_id = update.effective_chat.id
        msg = (
            "🤖 <b>Personal AI Startup & Job Outreach Bot</b>\n\n"
            f"Your Chat ID: <code>{user_chat_id}</code>\n\n"
            "<b>Available Commands:</b>\n"
            "• <code>/review</code> — Review all opportunities pending approval\n"
            "• <code>/clear</code> — Clear pending reviews and backlog queue (e.g. <code>/clear reviews</code>)\n"
            "• <code>/status</code> — View discovery & outreach metrics\n"
            "• <code>/profile</code> — View your profile & targeting criteria\n"
            "• <code>/discover [source]</code> — Trigger on-demand discovery (e.g. <code>/discover yc</code>)\n"
            "• <code>/sources</code> — List all 11 discovery connectors\n"
            "• <code>/set min_score [number]</code> — Update minimum fit score (e.g. <code>/set min_score 80</code>)\n"
            "• <code>/dry_run [on|off]</code> — Toggle dry-run email sending mode\n"
            "• <code>/logs</code> — View recent diagnostic logs for debugging\n"
            "• <code>/help</code> — Show this menu\n"
        )
        await update.message.reply_text(msg, parse_mode=ParseMode.HTML)

    async def cmd_review(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Handle /review command — send cards for all opportunities pending approval."""
        if not self.is_authorized(update):
            return

        from db.database import get_pending_approval_opportunities

        pending = get_pending_approval_opportunities(limit=10)
        if not pending:
            await update.message.reply_text(
                "✅ <b>No pending approvals!</b> All caught up.\nUse <code>/discover yc</code> to sweep for new startups.",
                parse_mode=ParseMode.HTML,
            )
            return

        await update.message.reply_text(
            f"📋 Found <b>{len(pending)} opportunity</b> waiting for your review:",
            parse_mode=ParseMode.HTML,
        )
        for item in pending:
            await self._send_opportunity_card(update.effective_chat.id, item, context)

    async def cmd_status(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Handle /status command."""
        if not self.is_authorized(update):
            return

        stats = get_system_stats()
        dry_run_tag = "🟡 DRY-RUN (Simulated)" if settings.DRY_RUN else "🟢 LIVE SMTP"

        msg = (
            f"📊 <b>Pipeline Statistics ({dry_run_tag})</b>\n\n"
            f"• <b>Total Companies Tracked:</b> {stats.get('total_companies', 0)}\n"
            f"• <b>Discovered Opportunities:</b> {stats.get('opportunities_discovered', 0)}\n"
            f"• <b>Pending Your Approval:</b> {stats.get('opportunities_pending_approval', 0)}\n"
            f"• <b>Total Outreach Sent:</b> {stats.get('total_sent', 0)}\n"
            f"• <b>Confirmed Replies:</b> {stats.get('total_replies', 0)}\n"
            f"• <b>Filtered Out:</b> {stats.get('opportunities_filtered', 0)}\n"
            f"• <b>Rejected:</b> {stats.get('opportunities_rejected', 0)}\n\n"
            "<i>Tip: Send <code>/review</code> to see pending cards.</i>"
        )
        await update.message.reply_text(msg, parse_mode=ParseMode.HTML)

    async def cmd_profile(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Handle /profile command."""
        if not self.is_authorized(update):
            return

        try:
            profile = load_user_profile()
            cand = profile.candidate
            targ = profile.targeting

            msg = (
                f"👤 <b>Candidate Profile: {cand.full_name}</b>\n\n"
                f"<b>Headline:</b> {cand.headline}\n"
                f"<b>Target Stages:</b> {', '.join(targ.target_stages)}\n"
                f"<b>Target Domains:</b> {', '.join(targ.target_domains[:4])}\n"
                f"<b>Target Roles:</b> {', '.join(targ.target_roles[:3])}\n"
                f"<b>Min Fit Score:</b> {targ.min_fit_score}/100\n"
                f"<b>Max Alerts/Day:</b> {targ.max_alerts_per_day}\n"
                f"<b>Location:</b> Remote Only ({', '.join(targ.location.prioritized_regions)})\n"
            )
            await update.message.reply_text(msg, parse_mode=ParseMode.HTML)
        except Exception as e:
            await update.message.reply_text(f"⚠️ Error loading profile: {e}")

    async def cmd_sources(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Display all available Track A and Track B discovery sources."""
        if not self.is_authorized(update):
            return

        msg = (
            "📡 <b>Available Discovery Sources</b>\n\n"
            "<b>Track A (Active Job Openings):</b>\n"
            "• <code>ashby</code> — Ashby public startup job boards\n"
            "• <code>greenhouse</code> — Greenhouse public startup boards\n"
            "• <code>lever</code> — Lever public startup boards\n\n"
            "<b>Track B (Early Startups, Launches & Stealth):</b>\n"
            "• <code>yc</code> — Y Combinator (W25, S24, W24, F24 batches)\n"
            "• <code>producthunt</code> — Product Hunt trending maker launches\n"
            "• <code>hackernews</code> (or <code>hn</code>) — Hacker News Launch HN & Show HN\n"
            "• <code>india</code> — Indian startup funding news (Inc42, Entrackr, YourStory)\n"
            "• <code>sec_edgar</code> — SEC Form D stealth venture fundings\n"
            "• <code>vc_stealth</code> — VC portfolio & stealth announcements\n"
            "• <code>tavily</code> — Live web search sweeps for stealth founders\n"
            "• <code>watchlist</code> — Hand-curated target startups\n"
            "• <code>all</code> — Run all 11 discovery connectors concurrently\n\n"
            "<b>Usage Examples:</b>\n"
            "• <code>/discover yc</code>\n"
            "• <code>/discover india</code>\n"
            "• <code>/discover producthunt</code>\n"
            "• <code>/discover all</code>"
        )
        await update.message.reply_text(msg, parse_mode=ParseMode.HTML)

    async def cmd_discover(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Handle /discover [source] command."""
        if not self.is_authorized(update):
            return

        args = context.args or []
        source = args[0].lower() if args else None

        # If user asked for list / help
        if source in ["list", "sources", "help"]:
            await self.cmd_sources(update, context)
            return

        from db.database import get_unscored_opportunity_ids

        await update.message.reply_text(
            f"🔍 <b>Triggering discovery sweep ({source or 'all sources'})...</b>\n"
            "<i>Evaluating matches against your profile and sending preview cards...</i>",
            parse_mode=ParseMode.HTML,
        )

        sources_to_run = [source] if source else None
        new_ids = await self.discovery_manager.run_discovery_sweep(sources=sources_to_run, limit_per_source=10)

        # If no new IDs discovered in this sweep, pick up unscored leads from backlog
        limit_to_process = new_ids[: settings.MAX_ALERTS_PER_DAY]
        if not limit_to_process:
            backlog_ids = get_unscored_opportunity_ids(limit=settings.MAX_ALERTS_PER_DAY)
            if backlog_ids:
                await update.message.reply_text(
                    f"📦 Found <b>{len(backlog_ids)} unscored opportunities</b> in backlog. Evaluating now...",
                    parse_mode=ParseMode.HTML,
                )
                limit_to_process = backlog_ids
            else:
                await update.message.reply_text("✅ All discovered opportunities have already been scored!")
                return

        matched_count = 0
        evaluated_summaries = []

        # Process opportunities through LangGraph pipeline with slight rate-limit throttling
        for i, opp_id in enumerate(limit_to_process):
            try:
                if i > 0:
                    await asyncio.sleep(1.5)  # 1.5s delay to prevent provider rate limits
                interrupt_payload = await self.orchestrator.process_opportunity(opp_id)
                if interrupt_payload and interrupt_payload.get("fit_score", 0) >= settings.MIN_FIT_SCORE:
                    matched_count += 1
                    await self._send_opportunity_card(update.effective_chat.id, interrupt_payload, context)
            except Exception as e:
                logger.error(f"Error processing opp #{opp_id}: {e}", exc_info=True)

            # Retrieve evaluation outcome for summary breakdown
            from db.database import get_opportunity_evaluation_summary
            summ = get_opportunity_evaluation_summary(opp_id)
            if summ:
                evaluated_summaries.append(summ)

        # Build comprehensive summary list of every opportunity evaluated
        lines = []
        for s in evaluated_summaries:
            opp_id = s.get("id")
            comp = html.escape(s.get("company_name") or "Unknown Company")
            title = html.escape(s.get("title") or "Opportunity")
            score = s.get("fit_score", 0)
            reason = s.get("summary_reasoning") or "Evaluated against candidate profile."
            if len(reason) > 120:
                reason = reason[:117] + "..."
            reason = html.escape(reason)

            if score >= settings.MIN_FIT_SCORE:
                badge = "🎯"
                status_label = f"<b>{score}/100</b> [Card Sent 📬]"
            elif score > 0:
                badge = "⚠️"
                status_label = f"<b>{score}/100</b> [Filtered Out]"
            else:
                badge = "🚫"
                status_label = f"<b>{score}/100</b> [Knockout]"

            lines.append(
                f"{badge} <b>#{opp_id} {comp}</b> — {title}\n"
                f"   • Score: {status_label}\n"
                f"   • Reason: <i>{reason}</i>\n"
            )

        # Send header & breakdown in chunks of 5
        chunk_size = 5
        total_eval = len(evaluated_summaries)
        
        header_text = (
            f"📊 <b>Discovery & Evaluation Breakdown</b>\n"
            f"• Total Evaluated: <b>{total_eval}</b>\n"
            f"• High-Fit Cards Sent: <b>{matched_count}</b> (Threshold: {settings.MIN_FIT_SCORE}/100)\n"
            f"• Filtered / Dropped: <b>{total_eval - matched_count}</b>\n"
            f"──────────────────────────\n"
        )

        if not lines:
            await update.message.reply_text(
                header_text + "ℹ️ No opportunities were evaluated in this run.",
                parse_mode=ParseMode.HTML,
            )
        else:
            for idx in range(0, len(lines), chunk_size):
                chunk = lines[idx : idx + chunk_size]
                chunk_msg = header_text if idx == 0 else ""
                chunk_msg += "\n".join(chunk)
                if idx + chunk_size >= len(lines):
                    chunk_msg += (
                        f"\n──────────────────────────\n"
                        f"Use <code>/review</code> to approve or customize pending drafts."
                    )
                try:
                    await update.message.reply_text(chunk_msg, parse_mode=ParseMode.HTML, disable_web_page_preview=True)
                except Exception as e:
                    logger.warning(f"HTML error sending summary chunk: {e}. Sending plain text.")
                    clean_chunk = re.sub(r"<[^>]+>", "", chunk_msg)
                    await update.message.reply_text(clean_chunk, disable_web_page_preview=True)

    async def cmd_logs(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Handle /logs command to view recent diagnostic log output."""
        if not self.is_authorized(update):
            return

        log_path = settings.LOG_FILE_PATH
        if not log_path.exists():
            await update.message.reply_text("ℹ️ No log file found yet.")
            return

        try:
            with open(log_path, "r", encoding="utf-8", errors="ignore") as f:
                lines = f.readlines()
                recent_lines = lines[-20:] if len(lines) >= 20 else lines
                log_snippet = "".join(recent_lines)

            if len(log_snippet) > 3500:
                log_snippet = log_snippet[-3500:]

            escaped = html.escape(log_snippet)
            await update.message.reply_text(
                f"📋 <b>Recent Diagnostic Logs:</b>\n<pre>{escaped}</pre>",
                parse_mode=ParseMode.HTML,
            )
        except Exception as e:
            await update.message.reply_text(f"⚠️ Error reading log file: {e}")

    async def cmd_set(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Handle /set [key] [value] command."""
        if not self.is_authorized(update):
            return

        args = context.args or []
        if len(args) < 2:
            await update.message.reply_text("Usage: <code>/set min_score 80</code>", parse_mode=ParseMode.HTML)
            return

        key, val = args[0].lower(), args[1]
        if key == "min_score":
            try:
                settings.MIN_FIT_SCORE = int(val)
                await update.message.reply_text(f"✅ Minimum fit score updated to {settings.MIN_FIT_SCORE}")
            except ValueError:
                await update.message.reply_text("⚠️ Score must be an integer (0-100).")
        else:
            await update.message.reply_text(f"⚠️ Unknown setting key: {key}")

    async def cmd_dry_run(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Handle /dry_run [on|off]."""
        if not self.is_authorized(update):
            return

        args = context.args or []
        if args and args[0].lower() in ["off", "false", "live"]:
            settings.DRY_RUN = False
            await update.message.reply_text("🟢 DRY-RUN mode disabled. Live emails will be dispatched via Gmail SMTP.")
        else:
            settings.DRY_RUN = True
            await update.message.reply_text("🟡 DRY-RUN mode enabled. Emails will be logged without real dispatch.")

    # ==========================================================================
    # 🔘 INLINE BUTTON CALLBACK HANDLERS
    # ==========================================================================

    async def handle_callback_query(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Route inline button clicks."""
        query = update.callback_query
        if not query or not self.is_authorized(update):
            return

        await query.answer()
        data = query.data or ""
        chat_id = str(update.effective_chat.id)

        try:
            await self._route_callback_query(query, data, chat_id)
        except Exception as e:
            # Never let a resume/DB/network error die silently - the old behavior here was to
            # let exceptions propagate into python-telegram-bot's internal error logging, which
            # meant an approval could fail with zero visible feedback in the chat.
            logger.error(f"Callback query handling failed for data={data!r}: {e}", exc_info=True)
            try:
                await query.message.reply_text(
                    f"⚠️ <b>Action failed:</b> {e}", parse_mode=ParseMode.HTML
                )
            except Exception:
                logger.error("Additionally failed to notify user of the callback error.", exc_info=True)

    async def _route_callback_query(self, query, data: str, chat_id: str) -> None:
        """Dispatch a single callback query action. Raised exceptions are caught by the caller."""
        # 1. Opportunity Actions
        if data.startswith("approve_"):
            opp_id = int(data.replace("approve_", ""))
            await query.edit_message_reply_markup(reply_markup=None)
            await query.message.reply_text("⏳ Resuming thread & dispatching email...")

            # Pass the current (possibly user-edited) draft text explicitly. The paused graph's
            # checkpointed state only holds the original AI-drafted subject/body - without this,
            # editing a draft via "Edit Draft" then tapping Approve would silently send the
            # original AI draft instead of the edited text, since node_human_gate only applies
            # edited_subject/edited_body from THIS resume payload, not from the drafts table.
            edited_subject, edited_body = None, None
            with get_db_connection() as conn:
                cursor = conn.cursor()
                cursor.execute(
                    "SELECT subject, body FROM outreach_drafts WHERE opportunity_id = ? ORDER BY id DESC LIMIT 1",
                    (opp_id,),
                )
                draft_row = cursor.fetchone()
                if draft_row:
                    edited_subject, edited_body = draft_row["subject"], draft_row["body"]

            result = await self.orchestrator.resume_opportunity(
                opp_id, action="approve", edited_subject=edited_subject, edited_body=edited_body
            )
            if result.get("is_sent"):
                await query.message.reply_text(f"✅ <b>Approved & Sent!</b> (Opp #{opp_id})", parse_mode=ParseMode.HTML)
            else:
                err = result.get("error_message", "Unknown error")
                await query.message.reply_text(f"⚠️ <b>Sending Failed:</b> {err}", parse_mode=ParseMode.HTML)

        elif data.startswith("edit_"):
            opp_id = int(data.replace("edit_", ""))
            self.user_sessions[chat_id] = {
                "mode": "awaiting_draft_edit",
                "opp_id": opp_id,
                "msg_id": query.message.message_id,
            }
            await query.message.reply_text(
                f"✏️ <b>Editing Draft for Opp #{opp_id}</b>\n\n"
                "Please reply directly to this message with your updated email body:",
                parse_mode=ParseMode.HTML,
            )

        elif data.startswith("email_"):
            opp_id = int(data.replace("email_", ""))
            self.user_sessions[chat_id] = {
                "mode": "awaiting_email_input",
                "opp_id": opp_id,
                "msg_id": query.message.message_id,
            }
            await query.message.reply_text(
                f"✍️ <b>Provide Email for Opp #{opp_id}</b>\n\n"
                "Please reply with the verified email address:",
                parse_mode=ParseMode.HTML,
            )

        elif data.startswith("reject_"):
            opp_id = int(data.replace("reject_", ""))
            await query.edit_message_reply_markup(reply_markup=None)
            await self.orchestrator.resume_opportunity(opp_id, action="reject")
            await query.message.reply_text(f"❌ Opp #{opp_id} marked as rejected.")

        elif data.startswith("skip_"):
            opp_id = int(data.replace("skip_", ""))
            await query.edit_message_reply_markup(reply_markup=None)
            await query.message.reply_text(f"⏭️ Opp #{opp_id} skipped.")

        # 2. Follow-Up Check-in Actions
        elif data.startswith("fu_replied_"):
            sent_id = int(data.replace("fu_replied_", ""))
            update_follow_up_status(sent_id, status="replied", notes="Confirmed via Telegram")

            # Feed this positive outcome back into pattern learning: if the email that got a
            # reply was a guessed pattern (e.g. 'first.last'), that pattern gets ranked higher
            # for future guesses at other companies.
            with get_db_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("SELECT contact_id FROM sent_history WHERE id = ?", (sent_id,))
                row = cursor.fetchone()
            if row and row["contact_id"]:
                pattern = get_pattern_used_for_contact(row["contact_id"])
                if pattern:
                    record_pattern_success(pattern)

            await query.edit_message_reply_markup(reply_markup=None)
            await query.message.reply_text("🎉 Fantastic! Thread marked as <b>Replied / In Conversation</b>.", parse_mode=ParseMode.HTML)

        elif data.startswith("fu_bump_"):
            sent_id = int(data.replace("fu_bump_", ""))
            await query.edit_message_reply_markup(reply_markup=None)
            await query.message.reply_text("📝 Generating 2-sentence follow-up bump...")
            # Trigger follow-up bump drafting
            # (handled by follow-up checker / draft generator)

        elif data.startswith("fu_snooze_"):
            sent_id = int(data.replace("fu_snooze_", ""))
            update_follow_up_status(sent_id, status="pending_check", notes="Snoozed 3 days")
            await query.edit_message_reply_markup(reply_markup=None)
            await query.message.reply_text("⏰ Snoozed follow-up check-in for 3 days.")

        elif data.startswith("fu_close_"):
            sent_id = int(data.replace("fu_close_", ""))
            update_follow_up_status(sent_id, status="closed", notes="Closed via Telegram")
            await query.edit_message_reply_markup(reply_markup=None)
            await query.message.reply_text("🔒 Follow-up thread closed.")

    async def cmd_clear(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Handle /clear [all|reviews|backlog] command."""
        if not self.is_authorized(update):
            return

        from db.database import (
            clear_all_pending_and_unexplored,
            clear_pending_reviews,
            clear_unexplored_backlog,
        )

        args = context.args or []
        target = args[0].lower() if args else "all"

        if target in ["reviews", "pending", "cards"]:
            count = clear_pending_reviews()
            msg = (
                f"🧹 <b>Pending Reviews Cleared!</b>\n\n"
                f"• Dismissed <b>{count}</b> pending approval cards.\n"
                "• Your review queue is now clean."
            )
        elif target in ["backlog", "unexplored", "unscored"]:
            count = clear_unexplored_backlog()
            msg = (
                f"🧹 <b>Unexplored Backlog Cleared!</b>\n\n"
                f"• Filtered <b>{count}</b> unscored backlog opportunities.\n"
                "• Ready for fresh discovery sweeps."
            )
        else:  # "all" or default
            pending_count, backlog_count = clear_all_pending_and_unexplored()
            msg = (
                f"🧹 <b>Full Cleanup Completed!</b>\n\n"
                f"• <b>Pending Reviews Cleared:</b> {pending_count}\n"
                f"• <b>Unexplored Backlog Cleared:</b> {backlog_count}\n\n"
                "✅ All pending cards and backlog queues are cleared."
            )

        await update.message.reply_text(msg, parse_mode=ParseMode.HTML)

    # ==========================================================================
    # 💬 TEXT MESSAGE LISTENER (FOR DRAFT EDITS & EMAIL INPUT)
    # ==========================================================================

    async def handle_text_message(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Handle incoming text replies for draft edits and manual email updates."""
        if not update.message or not update.message.text or not self.is_authorized(update):
            return

        chat_id = str(update.effective_chat.id)
        session = self.user_sessions.get(chat_id)
        if not session:
            return

        text = update.message.text.strip()
        opp_id = session.get("opp_id")
        mode = session.get("mode")

        if mode == "awaiting_draft_edit":
            del self.user_sessions[chat_id]
            # Fetch draft ID for this opportunity and update
            with get_db_connection() as conn:
                cursor = conn.cursor()
                cursor.execute(
                    "SELECT id FROM outreach_drafts WHERE opportunity_id = ? ORDER BY id DESC LIMIT 1",
                    (opp_id,),
                )
                row = cursor.fetchone()
                if row:
                    update_draft_body(row["id"], body=text, status="edited", notes="Edited via Telegram")

            from db.database import get_opportunity_card_payload
            card_payload = get_opportunity_card_payload(opp_id)

            if card_payload:
                card_payload["draft_body"] = text
                await self._send_opportunity_card(update.effective_chat.id, card_payload, context)
            else:
                from telegram import InlineKeyboardButton, InlineKeyboardMarkup
                buttons = [
                    [
                        InlineKeyboardButton("✅ Approve & Send", callback_data=f"approve_{opp_id}"),
                        InlineKeyboardButton("✏️ Edit Draft", callback_data=f"edit_{opp_id}"),
                    ],
                    [
                        InlineKeyboardButton("❌ Reject", callback_data=f"reject_{opp_id}"),
                    ],
                ]
                await update.message.reply_text(
                    f"✅ <b>Draft updated for Opp #{opp_id}!</b>\n\n"
                    f"<b>Updated Email Text:</b>\n────────────────\n{html.escape(text)}\n────────────────\n\n"
                    f"Tap <b>Approve & Send</b> to dispatch.",
                    reply_markup=InlineKeyboardMarkup(buttons),
                    parse_mode=ParseMode.HTML,
                )

        elif mode == "awaiting_email_input":
            del self.user_sessions[chat_id]
            # Validate basic email syntax
            if not re.match(r"[^@]+@[^@]+\.[^@]+", text):
                await update.message.reply_text("⚠️ Invalid email format. Please try again.")
                return

            with get_db_connection() as conn:
                cursor = conn.cursor()
                cursor.execute(
                    """
                    SELECT c.id FROM contacts c
                    JOIN opportunities o ON c.company_id = o.company_id
                    WHERE o.id = ? LIMIT 1
                    """,
                    (opp_id,),
                )
                row = cursor.fetchone()
                if row:
                    update_contact_email(row["id"], email=text, confidence="verified")

            from db.database import get_opportunity_card_payload
            card_payload = get_opportunity_card_payload(opp_id)

            if card_payload:
                card_payload["contact_email"] = text
                card_payload["email_confidence"] = "verified"
                await self._send_opportunity_card(update.effective_chat.id, card_payload, context)
            else:
                from telegram import InlineKeyboardButton, InlineKeyboardMarkup
                buttons = [
                    [
                        InlineKeyboardButton("✅ Approve & Send", callback_data=f"approve_{opp_id}"),
                        InlineKeyboardButton("✏️ Edit Draft", callback_data=f"edit_{opp_id}"),
                    ],
                    [
                        InlineKeyboardButton("❌ Reject", callback_data=f"reject_{opp_id}"),
                    ],
                ]
                await update.message.reply_text(
                    f"✅ <b>Email saved for Opp #{opp_id}:</b> <code>{html.escape(text)}</code>\n\n"
                    f"Tap <b>Approve & Send</b> to dispatch.",
                    reply_markup=InlineKeyboardMarkup(buttons),
                    parse_mode=ParseMode.HTML,
                )

    # ==========================================================================
    # 🚀 BOT INITIALIZATION & POLLING
    # ==========================================================================

    def build_application(self) -> Application:
        """Construct and configure the python-telegram-bot application."""
        if not self.token:
            raise ValueError("TELEGRAM_BOT_TOKEN is not configured in .env")

        app = ApplicationBuilder().token(self.token).build()

        # Add Command Handlers
        app.add_handler(CommandHandler("start", self.cmd_start))
        app.add_handler(CommandHandler("help", self.cmd_start))
        app.add_handler(CommandHandler("review", self.cmd_review))
        app.add_handler(CommandHandler("clear", self.cmd_clear))
        app.add_handler(CommandHandler("purge", self.cmd_clear))
        app.add_handler(CommandHandler("sources", self.cmd_sources))
        app.add_handler(CommandHandler("status", self.cmd_status))
        app.add_handler(CommandHandler("profile", self.cmd_profile))
        app.add_handler(CommandHandler("discover", self.cmd_discover))
        app.add_handler(CommandHandler("logs", self.cmd_logs))
        app.add_handler(CommandHandler("set", self.cmd_set))
        app.add_handler(CommandHandler("dry_run", self.cmd_dry_run))

        # Add Callback Query & Message Handlers
        app.add_handler(CallbackQueryHandler(self.handle_callback_query))
        app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, self.handle_text_message))

        self.app = app
        return app
