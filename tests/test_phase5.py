"""Unit tests for Phase 5: Telegram Bot Cards & Controller."""

import pytest

from bot.card_renderer import render_follow_up_card, render_opportunity_card
from bot.telegram_bot import TelegramBotController


def test_render_opportunity_card_verified_email():
    """Test card rendering with verified email."""
    payload = {
        "opportunity_id": 101,
        "opportunity_type": "founder_reachout",
        "fit_score": 94,
        "company_name": "CodeMorph AI",
        "company_domain": "codemorph.dev",
        "funding_summary": "YC W25 • $3.2M Seed",
        "contact_name": "Alex Rivera",
        "contact_title": "Co-Founder & CTO",
        "contact_email": "alex@codemorph.dev",
        "email_confidence": "verified",
        "linkedin_url": "https://linkedin.com/in/alexrivera",
        "summary_reasoning": "Strong match with distributed agent workflows",
        "draft_subject": "Building CodeMorph's agent engine",
        "draft_body": "Hi Alex,\n\nLoved seeing CodeMorph launch.\n\nBest,\nAnurag",
    }

    text, keyboard = render_opportunity_card(payload)
    assert "FOUNDER OUTREACH MATCH" in text
    assert "94/100" in text
    assert "CodeMorph AI" in text
    assert "alex@codemorph.dev" in text
    assert "Verified" in text
    assert "https://linkedin.com/in/alexrivera" in text

    # Verify buttons
    buttons = keyboard.inline_keyboard
    assert any(b.callback_data == "approve_101" for row in buttons for b in row)
    assert any(b.callback_data == "edit_101" for row in buttons for b in row)
    assert any(b.callback_data == "email_101" for row in buttons for b in row)
    assert any(b.callback_data == "reject_101" for row in buttons for b in row)


def test_render_opportunity_card_low_confidence_badge():
    """Test card rendering with low confidence email badge."""
    payload = {
        "opportunity_id": 102,
        "opportunity_type": "stealth_reachout",
        "fit_score": 85,
        "company_name": "StealthCo",
        "company_domain": "stealth.ai",
        "contact_name": "Sarah Chen",
        "contact_email": "sarah@stealth.ai",
        "email_confidence": "low_confidence",
        "linkedin_url": "https://linkedin.com/in/sarahchen",
        "summary_reasoning": "Stealth seed round",
        "draft_subject": "Connecting with Sarah",
        "draft_body": "Hi Sarah,\n\nIntro.",
    }

    text, keyboard = render_opportunity_card(payload)
    assert "STEALTH STARTUP MATCH" in text
    assert "Low Confidence / Pattern Guess" in text


def test_render_follow_up_card():
    """Test follow-up check-in card rendering."""
    item = {
        "id": 55,
        "company_name": "Agentic AI",
        "contact_name": "Sam Altman",
        "recipient_email": "sam@agentic.ai",
        "sent_at": "2026-08-10 10:00:00",
        "subject": "Building Agentic AI",
    }

    text, keyboard = render_follow_up_card(item)
    assert "OUTREACH FOLLOW-UP CHECK-IN" in text
    assert "Agentic AI" in text
    assert "sam@agentic.ai" in text

    buttons = keyboard.inline_keyboard
    assert any(b.callback_data == "fu_replied_55" for row in buttons for b in row)
    assert any(b.callback_data == "fu_bump_55" for row in buttons for b in row)


def test_bot_authorization():
    """Test bot authorization check against chat ID."""
    bot = TelegramBotController(token="123456:dummy", authorized_chat_id="998877")
    assert bot.authorized_chat_id == "998877"
