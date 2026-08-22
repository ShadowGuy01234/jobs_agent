"""Pydantic structured schemas for LLM analysis, scoring, and drafting."""

from typing import List, Optional
from pydantic import BaseModel, Field


class EnrichedCompanyData(BaseModel):
    name: str = Field(description="Clean company name")
    domain: Optional[str] = Field(default=None, description="Company root domain, e.g. linear.app")
    stage: str = Field(default="seed", description="Stage: pre_seed, seed, series_a, series_b, series_c, growth, unknown")
    one_liner: str = Field(description="1-sentence description of what the company builds")
    tech_stack: List[str] = Field(default_factory=list, description="Primary technical stack, tools, and languages")
    founders: List[str] = Field(default_factory=list, description="Names of founders or key executives if identified")
    is_stealth: bool = Field(default=False, description="Whether the company is in stealth mode")
    funding_summary: Optional[str] = Field(default=None, description="Recent funding amount and investors")


class FitEvaluationResult(BaseModel):
    fit_score: int = Field(ge=0, le=100, description="Overall fit score from 0 to 100")
    decision: str = Field(description="PROCEED if fit_score >= threshold and no knockouts, else DROP")
    summary_reasoning: str = Field(description="2-3 sentence executive reasoning for this fit score")
    key_synergies: List[str] = Field(default_factory=list, description="Key technical and strategic synergies")
    potential_risks: List[str] = Field(default_factory=list, description="Any potential mismatches or risks")
    personalized_hook: str = Field(description="Specific technical observation or milestone to reference in outreach")
    knockout_triggered: Optional[str] = Field(default=None, description="Reason if a knockout rule was triggered")


class ContactInfoResult(BaseModel):
    name: str = Field(description="Full name of target person (Founder, CTO, or Hiring Lead)")
    title: str = Field(description="Role title (e.g. Co-Founder & CTO, Head of Engineering)")
    email: Optional[str] = Field(default=None, description="Email address if found")
    email_confidence: str = Field(default="missing", description="verified, low_confidence, or missing")
    linkedin_url: Optional[str] = Field(default=None, description="LinkedIn profile URL if found")
    twitter_url: Optional[str] = Field(default=None, description="Twitter / X profile URL if found")
    pattern_used: Optional[str] = Field(
        default=None,
        description="Internal only - which guess pattern (e.g. 'first.last') produced `email`, if it was inferred rather than found verbatim. Leave null.",
    )


class OutreachDraftResult(BaseModel):
    subject: str = Field(description="Direct, high-converting cold email subject line")
    body: str = Field(description="Personalized email body under 120 words following style rules")
    personalization_hook: str = Field(description="Specific milestone or technical detail referenced")
    word_count: int = Field(description="Word count of email body")
