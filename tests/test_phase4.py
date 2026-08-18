"""Unit tests for Phase 4: LangGraph StateGraph, Checkpointing & Pause/Resume Gate."""

import gc
import tempfile
from pathlib import Path
import pytest

from unittest.mock import AsyncMock, patch

from db.database import (
    get_or_create_company,
    init_db,
    save_opportunity,
)
from pipeline.orchestrator import PipelineOrchestrator
from pipeline.schemas import (
    ContactInfoResult,
    EnrichedCompanyData,
    FitEvaluationResult,
    OutreachDraftResult,
)


@pytest.fixture
def temp_db():
    """Create a fresh temporary SQLite database."""
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db_path = Path(f.name)
    init_db(db_path)
    yield db_path
    gc.collect()
    try:
        if db_path.exists():
            db_path.unlink()
        wal = db_path.with_suffix(".db-wal")
        shm = db_path.with_suffix(".db-shm")
        if wal.exists():
            wal.unlink()
        if shm.exists():
            shm.unlink()
    except (PermissionError, OSError):
        pass


@pytest.mark.asyncio
async def test_langgraph_pause_and_approve_resume(temp_db):
    """Test graph execution pausing at human gate and resuming on approve."""
    # Insert test opportunity
    company_id = get_or_create_company(
        domain="cursor.com",
        name="Cursor",
        website="https://cursor.com",
        stage="series_a",
        source="watchlist",
        description="AI code editor built for pair programming",
        tech_stack=["Python", "TypeScript", "LLM Inference"],
        country="Remote",
        db_path=temp_db,
    )
    opp_id = save_opportunity(
        company_id=company_id,
        type_="founder_reachout",
        title="Cursor AI Founding Engineer",
        url="https://cursor.com/careers/test-1",
        raw_content="Building autonomous code intelligence pair programmer",
        db_path=temp_db,
    )

    mock_enriched = EnrichedCompanyData(
        name="Cursor",
        domain="cursor.com",
        stage="series_a",
        one_liner="AI code editor",
        tech_stack=["Python", "TypeScript"],
    )
    mock_eval = FitEvaluationResult(
        fit_score=92,
        decision="PROCEED",
        summary_reasoning="Strong technical alignment",
        key_synergies=["Python", "LLMs"],
        potential_risks=[],
        personalized_hook="Cursor editor launch",
    )
    mock_contact = ContactInfoResult(
        name="Michael Truell",
        title="Co-Founder & CEO",
        email="michael@cursor.com",
        email_confidence="verified",
        linkedin_url="https://linkedin.com/in/michaeltruell",
    )
    mock_draft = OutreachDraftResult(
        subject="Building Cursor's agent runtime",
        body="Hi Michael,\n\nLoved seeing Cursor's latest release. Would love to help build your core engine.\n\nBest,\nAnurag",
        personalization_hook="Cursor editor launch",
        word_count=20,
    )

    with patch("pipeline.graph.extract_and_enrich", AsyncMock(return_value=mock_enriched)), \
         patch("pipeline.graph.score_opportunity_fit", AsyncMock(return_value=mock_eval)), \
         patch("pipeline.graph.research_contact", AsyncMock(return_value=mock_contact)), \
         patch("pipeline.graph.draft_personalized_outreach", AsyncMock(return_value=mock_draft)):

        orchestrator = PipelineOrchestrator(db_path=temp_db)

        # 2. Process opportunity -> should pause at human gate
        interrupt_payload = await orchestrator.process_opportunity(opp_id)
        assert interrupt_payload is not None
        assert interrupt_payload["opportunity_id"] == opp_id
        assert interrupt_payload["fit_score"] == 92
        assert interrupt_payload["contact_email"] == "michael@cursor.com"
        assert len(interrupt_payload["draft_body"]) > 0

        # 3. Resume with 'approve' action
        result = await orchestrator.resume_opportunity(
            opportunity_id=opp_id,
            action="approve",
        )
        assert result is not None
        assert result.get("is_sent") is True


@pytest.mark.asyncio
async def test_langgraph_reject_resume(temp_db):
    """Test graph execution pausing and resuming on reject."""
    company_id = get_or_create_company(
        domain="tavily.com",
        name="Tavily",
        website="https://tavily.com",
        stage="seed",
        source="watchlist",
        description="Search engine for AI agents",
        tech_stack=["Python", "FastAPI"],
        country="Remote",
        db_path=temp_db,
    )
    opp_id = save_opportunity(
        company_id=company_id,
        type_="founder_reachout",
        title="Tavily AI Core Reachout",
        url="https://tavily.com/careers/test-2",
        raw_content="Search API for AI agents and LLM web search",
        db_path=temp_db,
    )

    mock_enriched = EnrichedCompanyData(name="Tavily", domain="tavily.com", stage="seed", one_liner="Search for AI")
    mock_eval = FitEvaluationResult(fit_score=88, decision="PROCEED", summary_reasoning="Good match", personalized_hook="Search API")
    mock_contact = ContactInfoResult(name="Founding Team", title="Leadership", email="team@tavily.com")
    mock_draft = OutreachDraftResult(subject="Connecting", body="Hi team,\n\nIntro.\n\nBest,\nAnurag", personalization_hook="Search API", word_count=10)

    with patch("pipeline.graph.extract_and_enrich", AsyncMock(return_value=mock_enriched)), \
         patch("pipeline.graph.score_opportunity_fit", AsyncMock(return_value=mock_eval)), \
         patch("pipeline.graph.research_contact", AsyncMock(return_value=mock_contact)), \
         patch("pipeline.graph.draft_personalized_outreach", AsyncMock(return_value=mock_draft)):

        orchestrator = PipelineOrchestrator(db_path=temp_db)

        # 1. Process opportunity -> pause
        interrupt_payload = await orchestrator.process_opportunity(opp_id)
        assert interrupt_payload is not None

        # 2. Resume with 'reject'
        result = await orchestrator.resume_opportunity(
            opportunity_id=opp_id,
            action="reject",
        )
        assert result is not None
        assert result.get("decision") == "REJECTED"

