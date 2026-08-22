"""LangGraph StateGraph definition for the outreach pipeline."""

import logging
from pathlib import Path
from typing import Any, Dict, Literal
from langgraph.graph import END, StateGraph
from langgraph.types import interrupt

from config import settings
from db.database import (
    get_pattern_success_rates,
    record_pattern_attempt,
    save_draft,
    save_evaluation,
    save_or_update_contact,
    update_opportunity_status,
)
from discovery.models import CompanyInfo, DiscoverySource, OpportunityType, RawOpportunity
from pipeline.nodes.draft_outreach import draft_personalized_outreach
from pipeline.nodes.extract_enrich import extract_and_enrich
from pipeline.nodes.research_contacts import research_contact
from pipeline.nodes.score_fit import score_opportunity_fit
from pipeline.nodes.send_outreach import execute_outreach_send
from pipeline.schemas import ContactInfoResult, EnrichedCompanyData, FitEvaluationResult
from pipeline.state import OpportunityPipelineState

logger = logging.getLogger(__name__)


# ==============================================================================
# 🧩 GRAPH NODES
# ==============================================================================


async def node_enrich(state: OpportunityPipelineState) -> Dict[str, Any]:
    """Node 1: Extract and normalize company details."""
    raw_opp = RawOpportunity(
        source=DiscoverySource.MANUAL,
        type=OpportunityType(state.opportunity_type),
        title=state.opportunity_title,
        url=state.opportunity_url,
        company=CompanyInfo(
            name=state.company_name,
            domain=state.company_domain,
            stage=state.enriched_stage,
        ),
        location=state.opportunity_location,
        is_remote=state.is_remote,
        raw_content=state.raw_content,
    )

    enriched = await extract_and_enrich(raw_opp)
    return {
        "company_name": enriched.name,
        "company_domain": enriched.domain or state.company_domain,
        "enriched_stage": enriched.stage,
        "enriched_one_liner": enriched.one_liner,
        "enriched_tech_stack": enriched.tech_stack,
        "is_stealth": enriched.is_stealth,
        "funding_summary": enriched.funding_summary,
    }


async def node_score(state: OpportunityPipelineState) -> Dict[str, Any]:
    """Node 2: Evaluate fit score (0-100) and knockout filters."""
    db_path = Path(state.db_path) if state.db_path else None
    company_data = EnrichedCompanyData(
        name=state.company_name,
        domain=state.company_domain,
        stage=state.enriched_stage,
        one_liner=state.enriched_one_liner or state.opportunity_title,
        tech_stack=state.enriched_tech_stack,
        is_stealth=state.is_stealth,
        funding_summary=state.funding_summary,
    )

    eval_res: FitEvaluationResult = await score_opportunity_fit(
        company_data=company_data,
        opportunity_title=state.opportunity_title,
        opportunity_type=state.opportunity_type,
        opportunity_location=state.opportunity_location,
        raw_content=state.raw_content,
    )

    # Persist evaluation to SQLite
    save_evaluation(
        opportunity_id=state.opportunity_id,
        fit_score=eval_res.fit_score,
        decision=eval_res.decision,
        summary_reasoning=eval_res.summary_reasoning,
        key_synergies=eval_res.key_synergies,
        potential_risks=eval_res.potential_risks,
        personalized_hook=eval_res.personalized_hook,
        db_path=db_path,
    )

    return {
        "fit_score": eval_res.fit_score,
        "decision": eval_res.decision,
        "summary_reasoning": eval_res.summary_reasoning,
        "key_synergies": eval_res.key_synergies,
        "potential_risks": eval_res.potential_risks,
        "personalized_hook": eval_res.personalized_hook,
    }


def should_proceed_after_score(
    state: OpportunityPipelineState,
) -> Literal["research_contact", "filter_out"]:
    """Conditional edge: proceed only if fit score meets threshold."""
    if state.decision == "PROCEED" and state.fit_score >= settings.MIN_FIT_SCORE:
        return "research_contact"
    return "filter_out"


async def node_filter_out(state: OpportunityPipelineState) -> Dict[str, Any]:
    """Archive opportunity when score is below threshold or knockout triggered."""
    db_path = Path(state.db_path) if state.db_path else None
    update_opportunity_status(state.opportunity_id, "filtered", db_path=db_path)
    logger.info(f"Opportunity [{state.opportunity_id}] {state.company_name} filtered out (Score: {state.fit_score})")
    return {"decision": "DROP"}


async def node_research(state: OpportunityPipelineState) -> Dict[str, Any]:
    """Node 3: Discover founder/HM, LinkedIn URL, and verified email."""
    db_path = Path(state.db_path) if state.db_path else None
    company_data = EnrichedCompanyData(
        name=state.company_name,
        domain=state.company_domain,
        stage=state.enriched_stage,
        one_liner=state.enriched_one_liner,
        tech_stack=state.enriched_tech_stack,
        is_stealth=state.is_stealth,
    )

    pattern_success_rates = get_pattern_success_rates(db_path=db_path)
    contact_res: ContactInfoResult = await research_contact(
        company_data, pattern_success_rates=pattern_success_rates
    )

    if contact_res.pattern_used:
        record_pattern_attempt(contact_res.pattern_used, db_path=db_path)

    # Persist contact to SQLite
    contact_id = save_or_update_contact(
        company_id=state.company_id,
        name=contact_res.name,
        title=contact_res.title,
        email=contact_res.email,
        email_confidence=contact_res.email_confidence,
        linkedin_url=contact_res.linkedin_url,
        twitter_url=contact_res.twitter_url,
        pattern_used=contact_res.pattern_used,
        db_path=db_path,
    )

    return {
        "contact_id": contact_id,
        "contact_name": contact_res.name,
        "contact_title": contact_res.title,
        "contact_email": contact_res.email,
        "email_confidence": contact_res.email_confidence,
        "linkedin_url": contact_res.linkedin_url,
    }


async def node_draft(state: OpportunityPipelineState) -> Dict[str, Any]:
    """Node 4: Craft hyper-personalized cold outreach draft."""
    db_path = Path(state.db_path) if state.db_path else None
    company_data = EnrichedCompanyData(
        name=state.company_name,
        domain=state.company_domain,
        stage=state.enriched_stage,
        one_liner=state.enriched_one_liner,
        tech_stack=state.enriched_tech_stack,
        is_stealth=state.is_stealth,
        funding_summary=state.funding_summary,
    )
    fit_eval = FitEvaluationResult(
        fit_score=state.fit_score,
        decision=state.decision,
        summary_reasoning=state.summary_reasoning,
        key_synergies=state.key_synergies,
        potential_risks=state.potential_risks,
        personalized_hook=state.personalized_hook,
    )
    contact_info = ContactInfoResult(
        name=state.contact_name,
        title=state.contact_title,
        email=state.contact_email,
        email_confidence=state.email_confidence,
        linkedin_url=state.linkedin_url,
    )

    draft_res = await draft_personalized_outreach(
        company_data=company_data,
        fit_eval=fit_eval,
        contact_info=contact_info,
        opportunity_type=state.opportunity_type,
    )

    # Persist draft to SQLite
    draft_id = save_draft(
        opportunity_id=state.opportunity_id,
        contact_id=state.contact_id,
        subject=draft_res.subject,
        body=draft_res.body,
        draft_type="initial",
        status="pending",
        db_path=db_path,
    )
    update_opportunity_status(state.opportunity_id, "pending_approval", db_path=db_path)

    return {
        "draft_id": draft_id,
        "draft_subject": draft_res.subject,
        "draft_body": draft_res.body,
        "draft_word_count": draft_res.word_count,
    }


async def node_human_gate(state: OpportunityPipelineState) -> Dict[str, Any]:
    """Node 5: Human-in-the-loop gate via LangGraph interrupt()."""
    # Create review payload for Telegram preview card
    payload = {
        "opportunity_id": state.opportunity_id,
        "company_name": state.company_name,
        "company_domain": state.company_domain,
        "fit_score": state.fit_score,
        "opportunity_type": state.opportunity_type,
        "summary_reasoning": state.summary_reasoning,
        "contact_name": state.contact_name,
        "contact_title": state.contact_title,
        "contact_email": state.contact_email,
        "email_confidence": state.email_confidence,
        "linkedin_url": state.linkedin_url,
        "draft_subject": state.draft_subject,
        "draft_body": state.draft_body,
    }

    # Pause execution durably until resumed with Command(resume=...)
    human_input = interrupt(payload)

    action = human_input.get("action", "skip")
    return {
        "human_action": action,
        "edited_subject": human_input.get("edited_subject"),
        "edited_body": human_input.get("edited_body"),
        "manually_provided_email": human_input.get("provided_email"),
    }


def should_proceed_after_human(
    state: OpportunityPipelineState,
) -> Literal["send_outreach", "reject_opportunity", "end"]:
    """Conditional edge after human resume."""
    if state.human_action == "approve":
        return "send_outreach"
    elif state.human_action == "reject":
        return "reject_opportunity"
    return "end"


async def node_reject(state: OpportunityPipelineState) -> Dict[str, Any]:
    """Mark opportunity as rejected by user."""
    db_path = Path(state.db_path) if state.db_path else None
    update_opportunity_status(state.opportunity_id, "rejected", db_path=db_path)
    logger.info(f"Opportunity [{state.opportunity_id}] rejected by user.")
    return {"decision": "REJECTED"}


async def node_send(state: OpportunityPipelineState) -> Dict[str, Any]:
    """Node 6: Send email via Gmail SMTP (only reached upon human approval)."""
    updated_state = await execute_outreach_send(state)
    return {
        "is_sent": updated_state.is_sent,
        "error_message": updated_state.error_message,
    }


# ==============================================================================
# 🏗️ GRAPH BUILDER
# ==============================================================================


def build_outreach_graph():
    """Build and compile the LangGraph StateGraph."""
    builder = StateGraph(OpportunityPipelineState)

    # Add Nodes
    builder.add_node("enrich", node_enrich)
    builder.add_node("score", node_score)
    builder.add_node("filter_out", node_filter_out)
    builder.add_node("research_contact", node_research)
    builder.add_node("draft", node_draft)
    builder.add_node("human_gate", node_human_gate)
    builder.add_node("send_outreach", node_send)
    builder.add_node("reject_opportunity", node_reject)

    # Set Entry Point
    builder.set_entry_point("enrich")

    # Connect Edges
    builder.add_edge("enrich", "score")

    # Conditional Routing After Scoring
    builder.add_conditional_edges(
        "score",
        should_proceed_after_score,
        {
            "research_contact": "research_contact",
            "filter_out": "filter_out",
        },
    )
    builder.add_edge("filter_out", END)

    builder.add_edge("research_contact", "draft")
    builder.add_edge("draft", "human_gate")

    # Conditional Routing After Human Gate
    builder.add_conditional_edges(
        "human_gate",
        should_proceed_after_human,
        {
            "send_outreach": "send_outreach",
            "reject_opportunity": "reject_opportunity",
            "end": END,
        },
    )
    builder.add_edge("send_outreach", END)
    builder.add_edge("reject_opportunity", END)

    return builder
