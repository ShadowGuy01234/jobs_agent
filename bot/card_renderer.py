"""Telegram message card formatters with rich Markdown/HTML formatting and inline keyboards."""

import html
from typing import Any, Dict, Optional
from telegram import InlineKeyboardButton, InlineKeyboardMarkup

from pipeline.timeslots import is_poor_send_window


def render_opportunity_card(payload: Dict[str, Any]) -> tuple[str, InlineKeyboardMarkup]:
    """Format opportunity preview card and inline action buttons for Telegram."""
    opp_id = payload["opportunity_id"]
    opp_type = payload.get("opportunity_type", "founder_reachout")
    score = payload.get("fit_score", 0)
    company = html.escape(str(payload.get("company_name", "Startup")))
    domain = html.escape(str(payload.get("company_domain", "")))
    milestone = html.escape(str(payload.get("funding_summary") or payload.get("enriched_stage", "Seed")))
    contact_name = html.escape(str(payload.get("contact_name", "Founding Team")))
    contact_title = html.escape(str(payload.get("contact_title", "Leadership")))
    contact_email = payload.get("contact_email")
    confidence = payload.get("email_confidence", "missing")
    linkedin = payload.get("linkedin_url")
    reasoning = html.escape(str(payload.get("summary_reasoning", "")))
    subject = html.escape(str(payload.get("draft_subject", "")))
    body = html.escape(str(payload.get("draft_body", "")))

    # Header Tag
    if opp_type == "stealth_reachout":
        header = f"🕵️ STEALTH STARTUP MATCH (Fit Score: {score}/100)"
    elif opp_type == "job_posting":
        header = f"💼 JOB OPENING MATCH (Fit Score: {score}/100)"
    else:
        header = f"🔥 FOUNDER OUTREACH MATCH (Fit Score: {score}/100)"

    # Email badge
    if contact_email and confidence == "verified":
        email_str = f"<code>{html.escape(str(contact_email))}</code> (✅ Verified)"
    elif contact_email and confidence == "low_confidence":
        email_str = f"<code>{html.escape(str(contact_email))}</code> (⚠️ Low Confidence / Pattern Guess)"
    elif contact_email:
        email_str = f"<code>{html.escape(str(contact_email))}</code>"
    else:
        email_str = "❌ <i>Email Missing (Provide below)</i>"

    # Advisory only - sending stays instant and manual (data/template_outrach.md:188).
    poor_window = is_poor_send_window()
    send_window_hint = (
        f"\n\n⏰ <i>Heads up: {html.escape(poor_window)}.</i>" if poor_window else ""
    )

    linkedin_str = f"<a href='{linkedin}'>LinkedIn Profile</a>" if linkedin else "<i>Not found</i>"
    website_str = f"<a href='https://{domain}'>{domain}</a>" if domain else "<i>N/A</i>"

    text = (
        f"<b>━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━</b>\n"
        f"<b>{header}</b>\n"
        f"<b>━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━</b>\n\n"
        f"🏢 <b>Company:</b> {company} ({website_str})\n"
        f"🚀 <b>Milestone/Stage:</b> {milestone}\n"
        f"👥 <b>Target:</b> {contact_name} ({contact_title})\n"
        f"🔗 <b>LinkedIn:</b> {linkedin_str}\n"
        f"📧 <b>Email:</b> {email_str}\n\n"
        f"💡 <b>Why It's a Fit:</b>\n"
        f"{reasoning}\n\n"
        f"📝 <b>Draft Outreach Preview:</b>\n"
        f"────────────────────────────────\n"
        f"<b>Subject:</b> {subject}\n\n"
        f"{body}\n"
        f"────────────────────────────────"
        f"{send_window_hint}"
    )

    # Action buttons
    buttons = [
        [
            InlineKeyboardButton("✅ Approve & Send", callback_data=f"approve_{opp_id}"),
            InlineKeyboardButton("✏️ Edit Draft", callback_data=f"edit_{opp_id}"),
        ],
        [
            InlineKeyboardButton("✍️ Provide Email", callback_data=f"email_{opp_id}"),
            InlineKeyboardButton("❌ Reject", callback_data=f"reject_{opp_id}"),
        ],
        [
            InlineKeyboardButton("⏭️ Skip", callback_data=f"skip_{opp_id}"),
        ],
    ]

    return text, InlineKeyboardMarkup(buttons)


def render_follow_up_card(item: Dict[str, Any]) -> tuple[str, InlineKeyboardMarkup]:
    """Format 5-7 day follow-up check-in card."""
    sent_id = item["id"]
    company = html.escape(str(item.get("company_name", "Company")))
    contact = html.escape(str(item.get("contact_name") or item.get("recipient_email", "")))
    email = html.escape(str(item.get("recipient_email", "")))
    sent_at = html.escape(str(item.get("sent_at", "")[:10]))
    subject = html.escape(str(item.get("subject", "")))

    text = (
        f"<b>━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━</b>\n"
        f"📬 <b>OUTREACH FOLLOW-UP CHECK-IN</b>\n"
        f"<b>━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━</b>\n\n"
        f"🏢 <b>Company:</b> {company}\n"
        f"👥 <b>Contact:</b> {contact} (<code>{email}</code>)\n"
        f"📅 <b>Sent Date:</b> {sent_at}\n"
        f"📝 <b>Subject:</b> {subject}\n\n"
        f"Did you receive a reply or schedule an intro call?"
    )

    buttons = [
        [
            InlineKeyboardButton("✅ Got Reply / Interview", callback_data=f"fu_replied_{sent_id}"),
            InlineKeyboardButton("❌ No Reply - Draft Bump", callback_data=f"fu_bump_{sent_id}"),
        ],
        [
            InlineKeyboardButton("⏭️ Snooze 3 Days", callback_data=f"fu_snooze_{sent_id}"),
            InlineKeyboardButton("🔒 Close Thread", callback_data=f"fu_close_{sent_id}"),
        ],
    ]

    return text, InlineKeyboardMarkup(buttons)
