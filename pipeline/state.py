"""LangGraph Typed State definitions for opportunity processing pipeline."""

from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field


class OpportunityPipelineState(BaseModel):
    # Identifiers & DB keys
    opportunity_id: int
    company_id: int
    thread_id: str
    db_path: Optional[str] = None

    # Raw opportunity data
    opportunity_title: str
    opportunity_type: str  # 'founder_reachout', 'stealth_reachout', 'job_posting'
    opportunity_url: str
    opportunity_location: str = "Remote"
    is_remote: bool = True
    raw_content: Optional[str] = None
    company_name: str
    company_domain: Optional[str] = None

    # Enriched company data
    enriched_stage: str = "seed"
    enriched_one_liner: str = ""
    enriched_tech_stack: List[str] = Field(default_factory=list)
    is_stealth: bool = False
    funding_summary: Optional[str] = None

    # Evaluation results
    fit_score: int = 0
    decision: str = "PENDING"  # 'PROCEED', 'DROP'
    summary_reasoning: str = ""
    key_synergies: List[str] = Field(default_factory=list)
    potential_risks: List[str] = Field(default_factory=list)
    personalized_hook: str = ""

    # Contact information
    contact_id: Optional[int] = None
    contact_name: str = "Founding Team"
    contact_title: str = "Leadership"
    contact_email: Optional[str] = None
    email_confidence: str = "missing"
    linkedin_url: Optional[str] = None

    # Drafted email
    draft_id: Optional[int] = None
    draft_subject: str = ""
    draft_body: str = ""
    draft_word_count: int = 0

    # Human Gate & Execution State
    human_action: Optional[str] = None  # 'approve', 'edit', 'reject', 'skip'
    edited_subject: Optional[str] = None
    edited_body: Optional[str] = None
    manually_provided_email: Optional[str] = None
    is_sent: bool = False
    error_message: Optional[str] = None
