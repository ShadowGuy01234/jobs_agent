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
async def test_contact_research_pattern_fallback():
    """Test contact research pattern matching and confidence badging."""
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
