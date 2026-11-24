"""Unit tests for Phase 3: AI Intelligence (Knockouts, Contact Research & Drafting)."""

import pytest

from profile.parser import load_user_profile
from pipeline.nodes.draft_outreach import draft_personalized_outreach
from pipeline.nodes.research_contacts import research_contact
from pipeline.nodes.score_fit import check_knockout_filters
from pipeline.schemas import (
    ContactInfoResult,
    EnrichedCompanyData,
    FitEvaluationResult,
)


def test_knockout_filters():
    """Test hard knockout filters for non-target stages and blacklisted sectors."""
    profile = load_user_profile()

    # 1. Non-target stage (e.g. Series E / Growth)
    company_growth = EnrichedCompanyData(
        name="MegaCorp",
        stage="series_e",
        one_liner="Enterprise database conglomerate",
    )
    knockout = check_knockout_filters(company_growth, "Principal Engineer", "Remote", profile)
    assert knockout is not None
    assert "series_e" in knockout

    # 2. Excluded sector (e.g. Crypto casino)
    company_casino = EnrichedCompanyData(
        name="CryptoBet",
        stage="seed",
        one_liner="Decentralized meme coins and online casino gambling games",
    )
    knockout_casino = check_knockout_filters(company_casino, "Backend Dev", "Remote", profile)
    assert knockout_casino is not None

    # 3. Valid company passes
    company_valid = EnrichedCompanyData(
        name="AgentMorph",
        stage="seed",
        one_liner="Autonomous test generation agents in Python",
        tech_stack=["Python", "FastAPI", "LangGraph"],
    )
    knockout_valid = check_knockout_filters(company_valid, "Founding Engineer", "Remote", profile)
    assert knockout_valid is None


@pytest.mark.asyncio
async def test_contact_research_pattern_fallback(monkeypatch):
    """Test contact research pattern matching and confidence badging without burning live APIs."""
    from unittest.mock import AsyncMock
    from pipeline.llm import LLMClient

    monkeypatch.setattr("pipeline.nodes.research_contacts.lookup_hunter_domain_search", AsyncMock(return_value=[]))
    monkeypatch.setattr("pipeline.nodes.research_contacts.lookup_hunter_email_finder", AsyncMock(return_value=None))
    monkeypatch.setattr("pipeline.nodes.research_contacts.scrape_website_emails", AsyncMock(return_value=[]))
    monkeypatch.setattr("pipeline.nodes.research_contacts.lookup_apollo_person", AsyncMock(return_value=None))
    monkeypatch.setattr("pipeline.nodes.research_contacts.settings.TAVILY_API_KEY", "")
    monkeypatch.setattr(
        LLMClient,
        "generate_structured",
        AsyncMock(
            return_value=ContactInfoResult(
                name="Alex Rivera",
                title="Founder & CEO",
                email=None,
                email_confidence="missing",
            )
        ),
    )

    company = EnrichedCompanyData(
        name="AgentMorph",
        domain="agentmorph.dev",
        stage="seed",
        one_liner="Autonomous agents",
        founders=["Alex Rivera"],
    )
    result = await research_contact(company)
    assert result.name == "Alex Rivera"
    assert result.email in ["alex@agentmorph.dev", "alex.rivera@agentmorph.dev"]
    assert result.email_confidence in ["verified", "low_confidence"]


@pytest.mark.asyncio
async def test_hunter_primary_contact_match(monkeypatch):
    """Hunter.io domain-search leadership hit short-circuits directly to a verified contact."""
    from unittest.mock import AsyncMock

    hunter_results = [
        {
            "value": "info@acme.ai",
            "type": "generic",
            "confidence": 99,
        },
        {
            "value": "jane@acme.ai",
            "type": "personal",
            "first_name": "Jane",
            "last_name": "Doe",
            "position": "Co-Founder & CTO",
            "seniority": "executive",
            "confidence": 94,
            "linkedin": "https://linkedin.com/in/janedoe",
            "verification": {"status": "valid"},
        },
    ]
    monkeypatch.setattr(
        "pipeline.nodes.research_contacts.lookup_hunter_domain_search",
        AsyncMock(return_value=hunter_results),
    )
    scrape_mock = AsyncMock(return_value=[])
    monkeypatch.setattr("pipeline.nodes.research_contacts.scrape_website_emails", scrape_mock)

    company = EnrichedCompanyData(
        name="Acme AI",
        domain="acme.ai",
        stage="seed",
        one_liner="AI agents",
    )
    result = await research_contact(company)
    assert result.name == "Jane Doe"
    assert result.email == "jane@acme.ai"
    assert result.email_confidence == "verified"
    assert result.linkedin_url == "https://linkedin.com/in/janedoe"
    scrape_mock.assert_not_awaited()


@pytest.mark.asyncio
async def test_hunter_email_finder_fallback(monkeypatch):
    """When domain-search has no hit but founder name is known, Hunter email-finder resolves it."""
    from unittest.mock import AsyncMock

    monkeypatch.setattr("pipeline.nodes.research_contacts.lookup_hunter_domain_search", AsyncMock(return_value=[]))
    monkeypatch.setattr(
        "pipeline.nodes.research_contacts.lookup_hunter_email_finder",
        AsyncMock(
            return_value={
                "email": "alex@agentmorph.dev",
                "score": 95,
                "position": "Founder & CEO",
                "verification": {"status": "valid"},
            }
        ),
    )

    company = EnrichedCompanyData(
        name="AgentMorph",
        domain="agentmorph.dev",
        stage="seed",
        one_liner="Autonomous agents",
        founders=["Alex Rivera"],
    )
    result = await research_contact(company)
    assert result.email == "alex@agentmorph.dev"
    assert result.email_confidence == "verified"


@pytest.mark.asyncio
async def test_follow_up_bump_drafting():
    """Test 2-sentence follow-up bump drafting."""
    profile = load_user_profile()
    company = EnrichedCompanyData(
        name="AgentMorph",
        stage="seed",
        one_liner="Autonomous agents",
    )
    fit_eval = FitEvaluationResult(
        fit_score=92,
        decision="PROCEED",
        summary_reasoning="Great fit",
        key_synergies=["Python"],
        potential_risks=[],
        personalized_hook="YC W25 Demo Day launch",
    )
    contact = ContactInfoResult(
        name="Alex Rivera",
        title="Founder & CEO",
        email="alex@agentmorph.dev",
    )

    draft = await draft_personalized_outreach(
        company_data=company,
        fit_eval=fit_eval,
        contact_info=contact,
        is_follow_up=True,
        original_subject="Building AgentMorph / YC W25",
        profile=profile,
    )

    assert "Re:" in draft.subject
    assert "Alex" in draft.body
    assert "Anurag" in draft.body
    assert draft.word_count < 60


def test_title_relevance_filter():
    """Non-engineering job titles are dropped before any LLM call; headlines are exempt."""
    from pipeline.nodes.score_fit import check_title_relevance

    for title in [
        "Enterprise Account Executive",
        "Payroll Tax Manager",
        "Technical Recruiter",
        "Customer Success Manager",
        "Retail Store Associate",
        "Registered Nurse",
        # Customer-facing "engineer" titles must lose to the pseudo-engineering check.
        "Sales Engineer",
        "Solutions Engineer",
        # Non-engineering roles containing generic words like "Platform".
        "Account Executive, Amer Platform (Growth Velocity)",
        # Regression: bare substring matching let "cto" match inside "Colle(cto)r".
        "Specimen Collector",
    ]:
        assert check_title_relevance(title, "job_posting") is not None, title

    for title in [
        "Founding AI Engineer",
        "Backend Engineer (Python)",
        "Software Engineer, Infrastructure",
        "Staff Software Engineer",
        "Member of Technical Staff",
        "Applied Scientist",
        "Senior Golang Developer",
        # Multi-role postings pass on their engineering half.
        "AI Research Engineer | Technical AEs",
    ]:
        assert check_title_relevance(title, "job_posting") is None, title

    # Founder/stealth "titles" are news headlines - keyword matching there is meaningless
    # and would silently drop good leads.
    assert check_title_relevance("Acme raises $5M to build AI sales agents", "founder_reachout") is None
    assert check_title_relevance("Stealth startup from ex-Director of Eng", "stealth_reachout") is None


def test_timeslots_are_future_business_days():
    """The scheduling ask must never propose a weekend or a day already past."""
    from datetime import datetime
    from zoneinfo import ZoneInfo
    from pipeline.timeslots import next_business_days

    tz = ZoneInfo("Asia/Kolkata")
    # Friday, Saturday and Sunday must all roll forward to the next working week.
    for day in (21, 22, 23):
        assert next_business_days(datetime(2026, 8, day, 9, 0, tzinfo=tz)) == ["Monday", "Tuesday"]

    for day in range(1, 29):
        got = next_business_days(datetime(2026, 8, day, 15, 0, tzinfo=tz))
        assert len(got) == 2
        assert not {"Saturday", "Sunday"} & set(got), got


def test_tokenrouter_llm_client_initialization():
    """Verify TokenRouter provider configures GLM 5.3 Flash and OpenAI client correctly."""
    from pipeline.llm import LLMClient
    from openai import OpenAI, AsyncOpenAI
    from langchain_openai import ChatOpenAI

    client = LLMClient(
        provider="tokenrouter",
        api_key="test-tr-key",
        base_url="https://api.tokenrouter.com/v1",
    )
    assert client.provider == "tokenrouter"
    assert client.base_url == "https://api.tokenrouter.com/v1"
    assert client.fast_model == "z-ai/glm-5.3-flash"
    assert client.smart_model == "z-ai/glm-5.3-flash"

    # Chat model instances
    fast_chat = client.get_fast_llm()
    assert isinstance(fast_chat, ChatOpenAI)
    assert fast_chat.model_name == "z-ai/glm-5.3-flash"
    assert str(fast_chat.openai_api_base) == "https://api.tokenrouter.com/v1"

    smart_chat = client.get_smart_llm()
    assert isinstance(smart_chat, ChatOpenAI)
    assert smart_chat.model_name == "z-ai/glm-5.3-flash"

    # Raw OpenAI SDK clients
    raw_client = client.get_openai_client()
    assert isinstance(raw_client, OpenAI)
    assert str(raw_client.base_url) == "https://api.tokenrouter.com/v1/"
    assert raw_client.api_key == "test-tr-key"

    async_client = client.get_async_openai_client()
    assert isinstance(async_client, AsyncOpenAI)
    assert str(async_client.base_url) == "https://api.tokenrouter.com/v1/"


@pytest.mark.asyncio
async def test_tokenrouter_structured_generation_mock(monkeypatch):
    """Test generate_structured with TokenRouter provider."""
    from unittest.mock import AsyncMock, MagicMock
    from pipeline.llm import LLMClient
    from pipeline.schemas import FitEvaluationResult

    client = LLMClient(provider="tokenrouter", api_key="dummy")

    mock_chat = MagicMock()
    mock_resp = MagicMock()
    mock_resp.content = (
        '{"fit_score": 88, "decision": "PROCEED", "summary_reasoning": "High synergy in distributed systems", '
        '"key_synergies": ["Python", "FastAPI"], "potential_risks": [], "personalized_hook": "Great work on LLMs"}'
    )
    mock_chat.ainvoke = AsyncMock(return_value=mock_resp)

    monkeypatch.setattr(client, "get_smart_llm", lambda: mock_chat)

    result = await client.generate_structured(
        prompt="Evaluate candidate",
        response_schema=FitEvaluationResult,
        use_smart=True,
    )
    assert isinstance(result, FitEvaluationResult)
    assert result.fit_score == 88
    assert result.decision == "PROCEED"


@pytest.mark.asyncio
async def test_llm_failover_on_non_rate_limit_error(monkeypatch):
    """Primary provider 404/503/timeout failures fail over cleanly to configured fallback providers."""
    from unittest.mock import AsyncMock, MagicMock
    from pipeline.llm import LLMClient
    from pipeline.schemas import FitEvaluationResult

    client = LLMClient(provider="tokenrouter", api_key="dummy-tr")

    failing_chat = MagicMock()
    failing_chat.model_name = "z-ai/glm-5.3-free"
    failing_chat.temperature = 0.2
    failing_chat.ainvoke = AsyncMock(side_effect=RuntimeError("Error code: 404 - model_not_found"))

    fallback_chat = MagicMock()
    fallback_chat.model_name = "openai/gpt-oss-120b"
    fallback_resp = MagicMock()
    fallback_resp.content = (
        '{"fit_score": 84, "decision": "PROCEED", "summary_reasoning": "Groq fallback succeeded", '
        '"key_synergies": ["Python"], "potential_risks": [], "personalized_hook": "Fast inference"}'
    )
    fallback_chat.ainvoke = AsyncMock(return_value=fallback_resp)

    monkeypatch.setattr(client, "get_smart_llm", lambda: failing_chat)
    monkeypatch.setattr(
        client,
        "_build_fallback_chat_model",
        lambda prov, use_smart, temperature: fallback_chat if prov == "groq" else None,
    )

    result = await client.generate_structured(
        prompt="Evaluate candidate",
        response_schema=FitEvaluationResult,
        use_smart=True,
    )
    assert result.fit_score == 84
    assert result.summary_reasoning == "Groq fallback succeeded"


def test_find_resume_pdf_detects_named_resume():
    """find_resume_pdf finds Anurag_Banerjee_Resume.pdf when profile/resume.pdf is absent."""
    from profile.parser import find_resume_pdf

    pdf = find_resume_pdf()
    assert pdf is not None
    assert pdf.exists()
    assert pdf.suffix.lower() == ".pdf"

