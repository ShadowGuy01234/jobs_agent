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


@pytest.mark.asyncio
async def test_approve_callback_forwards_email_and_distinguishes_dry_run(tmp_path, monkeypatch):
    """Approve callback passes updated SQLite contact email and clearly labels DRY_RUN vs live sends."""
    from unittest.mock import AsyncMock, MagicMock
    from config import settings
    from db.database import (
        get_or_create_company,
        init_db,
        save_draft,
        save_opportunity,
        save_or_update_contact,
    )
    import bot.telegram_bot as tb

    db_path = tmp_path / "bot_test.db"
    init_db(db_path)
    monkeypatch.setattr(settings, "DATABASE_PATH", db_path)

    cid = get_or_create_company(domain="acme.ai", name="Acme AI", db_path=db_path)
    oid = save_opportunity(cid, "founder_reachout", "Acme AI", "https://acme.ai", db_path=db_path)
    contact_id = save_or_update_contact(
        cid, "Jane Doe", email="jane@acme.ai", email_confidence="verified", db_path=db_path
    )
    save_draft(oid, contact_id, subject="Quick note", body="Draft body", db_path=db_path)

    bot = TelegramBotController(token="123456:dummy", authorized_chat_id="998877")
    resume_mock = AsyncMock(return_value={"is_sent": True, "contact_email": "jane@acme.ai"})
    monkeypatch.setattr(bot.orchestrator, "resume_opportunity", resume_mock)

    query = MagicMock()
    query.edit_message_reply_markup = AsyncMock()
    query.message.reply_text = AsyncMock()

    orig_dry = settings.DRY_RUN
    try:
        settings.DRY_RUN = True
        await bot._route_callback_query(query, f"approve_{oid}", "998877")
        assert resume_mock.await_args.kwargs["provided_email"] == "jane@acme.ai"
        last_text = query.message.reply_text.await_args_list[-1].args[0]
        assert "DRY-RUN" in last_text
        assert "jane@acme.ai" in last_text

        settings.DRY_RUN = False
        await bot._route_callback_query(query, f"approve_{oid}", "998877")
        last_text_live = query.message.reply_text.await_args_list[-1].args[0]
        assert "Live Email Sent" in last_text_live
        assert "jane@acme.ai" in last_text_live
    finally:
        settings.DRY_RUN = orig_dry


@pytest.mark.asyncio
async def test_shared_post_ingestion_preseeds_verified_email(tmp_path, monkeypatch):
    """WhatsApp/LinkedIn shared posts extract direct email and pre-seed a verified contact."""
    from unittest.mock import AsyncMock
    from config import settings
    from db.database import get_verified_company_contact, init_db
    from pipeline.ingest import SharedPostExtraction, ingest_and_process_shared_post, looks_like_job_post
    from pipeline.llm import LLMClient

    db_path = tmp_path / "ingest_test.db"
    init_db(db_path)
    monkeypatch.setattr(settings, "DATABASE_PATH", db_path)

    sample_post = (
        "#hiring #interns | Alok Singh\n"
        "Saraswati AI is Hiring Engineering Interns\n"
        "Mail here : tech@mysaraswati.in\n"
        "https://www.linkedin.com/posts/alokthegeek_hiring-interns"
    )
    assert looks_like_job_post(sample_post) is True
    assert looks_like_job_post("hi") is False

    monkeypatch.setattr(
        LLMClient,
        "generate_structured",
        AsyncMock(
            return_value=SharedPostExtraction(
                company_name="Saraswati AI",
                domain="mysaraswati.in",
                role_title="Engineering Intern",
                opportunity_type="job_posting",
                stage="seed",
                one_liner="AI education startup",
                contact_name="Alok Singh",
                contact_title="Founder",
                contact_email="tech@mysaraswati.in",
            )
        ),
    )

    mock_orch = AsyncMock()
    mock_orch.process_opportunity = AsyncMock(
        return_value={
            "opportunity_id": 1,
            "company_name": "Saraswati AI",
            "fit_score": 85,
            "contact_email": "tech@mysaraswati.in",
        }
    )

    res = await ingest_and_process_shared_post(
        text=sample_post,
        orchestrator=mock_orch,
        db_path=db_path,
    )
    assert res["duplicate"] is False
    assert res["interrupt_payload"]["contact_email"] == "tech@mysaraswati.in"
    cached = get_verified_company_contact(1, db_path=db_path)
    assert cached is not None
    assert cached["email"] == "tech@mysaraswati.in"


@pytest.mark.asyncio
async def test_bot_text_message_ingests_forwarded_post(monkeypatch):
    """Text messages outside draft-edit sessions ingest forwarded job posts and send a card."""
    from unittest.mock import AsyncMock, MagicMock

    bot = TelegramBotController(token="123456:dummy", authorized_chat_id="998877")
    fake_payload = {
        "opportunity_id": 77,
        "company_name": "Saraswati AI",
        "fit_score": 86,
        "contact_email": "tech@mysaraswati.in",
        "email_confidence": "verified",
        "draft_subject": "Quick note",
        "draft_body": "Hi Alok",
    }
    monkeypatch.setattr(
        "pipeline.ingest.ingest_and_process_shared_post",
        AsyncMock(return_value={"duplicate": False, "interrupt_payload": fake_payload}),
    )
    send_card_spy = AsyncMock()
    monkeypatch.setattr(bot, "_send_opportunity_card", send_card_spy)

    update = MagicMock()
    update.effective_chat.id = 998877
    update.effective_user.username = "testuser"
    update.message.text = "Saraswati AI is Hiring Engineering Interns\nMail here: tech@mysaraswati.in"
    update.message.reply_text = AsyncMock()

    await bot.handle_text_message(update, MagicMock())
    send_card_spy.assert_awaited_once()
    assert send_card_spy.await_args.args[1]["opportunity_id"] == 77


@pytest.mark.asyncio
async def test_bot_add_and_remove_telegram_channel(tmp_path, monkeypatch):
    """Bot commands /add_channel, /channels, /remove_channel persist and validate handles."""
    from unittest.mock import AsyncMock, MagicMock
    from config import settings
    from db.database import init_db
    import discovery.company_launch.telegram_channels as tc

    db_path = tmp_path / "channels_test.db"
    init_db(db_path)
    monkeypatch.setattr(settings, "DATABASE_PATH", db_path)

    assert tc.normalize_channel_handle("https://t.me/s/gocareers/") == "gocareers"
    assert tc.normalize_channel_handle("@internfreak") == "internfreak"
    assert tc.normalize_channel_handle("https://t.me/+AbCdEfG123") is None

    monkeypatch.setattr(tc, "validate_public_channel", AsyncMock(return_value=(True, 18, "ok")))

    bot = TelegramBotController(token="123456:dummy", authorized_chat_id="998877")

    def make_update(args):
        u = MagicMock()
        u.effective_chat.id = 998877
        u.effective_user.username = "testuser"
        u.message.reply_text = AsyncMock()
        ctx = MagicMock()
        ctx.args = list(args)
        return u, ctx

    # 1. Reject private invite link
    u, ctx = make_update(["https://t.me/+privateInvite"])
    await bot.cmd_add_channel(u, ctx)
    assert "private" in u.message.reply_text.await_args.args[0].lower()

    # 2. Add valid channel
    u, ctx = make_update(["https://t.me/my_new_jobs"])
    await bot.cmd_add_channel(u, ctx)
    assert "Added" in u.message.reply_text.await_args.args[0]
    assert "my_new_jobs" in tc.get_active_telegram_channels()

    # 3. List channels
    u, ctx = make_update([])
    await bot.cmd_channels(u, ctx)
    assert "my_new_jobs" in u.message.reply_text.await_args.args[0]

    # 4. Remove channel
    u, ctx = make_update(["@my_new_jobs"])
    await bot.cmd_remove_channel(u, ctx)
    assert "Removed" in u.message.reply_text.await_args.args[0]
    assert "my_new_jobs" not in tc.get_active_telegram_channels()
