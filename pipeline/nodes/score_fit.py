"""Candidate fit scoring node with knockout filters and 0-100 rubric."""

import logging
import re
from typing import Optional

from profile.models import UserProfile
from profile.parser import load_user_profile
from pipeline.llm import LLMClient
from pipeline.schemas import EnrichedCompanyData, FitEvaluationResult

logger = logging.getLogger(__name__)

# Customer-facing roles that contain "engineer" but are not engineering jobs. Checked first,
# because the allowlist below would otherwise wave them straight through.
PSEUDO_ENGINEERING_TITLES = (
    "sales engineer", "solutions engineer", "solution engineer", "support engineer",
    "customer engineer", "field engineer", "implementation engineer", "sales engineering",
)

# An allowlist rather than a blocklist: aggregator feeds carry retail, medical and teaching
# roles, and no blocklist can enumerate every non-tech job. Requiring a positive engineering
# signal is both shorter and tighter. Postings that bundle several roles ("AI Research Engineer
# | Technical AEs") still pass on the engineering half, which is what we want.
ENGINEERING_TITLE_KEYWORDS = (
    "engineer", "engineering", "developer", "programmer", "swe", "sde", "architect", "sre",
    "devops", "backend", "back-end", "frontend", "front-end", "fullstack", "full-stack",
    "full stack", "infrastructure", "platform", "data scientist", "scientist",
    "machine learning", "technical staff", "founding", "cto", "research",
)

# Matched on word boundaries, never as bare substrings: plain `in` matching let "cto" hit
# "Specimen Colle(cto)r" and wave a lab job through the filter.
_ENGINEERING_RE = re.compile(
    r"\b(" + "|".join(re.escape(k) for k in ENGINEERING_TITLE_KEYWORDS) + r")\b", re.I
)


def check_title_relevance(opp_title: str, opportunity_type: str) -> Optional[str]:
    """Reject job titles with no engineering signal before spending a smart-model call.

    Job boards and aggregators return every opening they have, so without this a "Payroll Tax
    Manager" or a "Retail Store Associate" costs a full LLM scoring call to land at 12/100.
    """
    if opportunity_type != "job_posting" or not opp_title:
        return None

    title_lower = opp_title.lower()

    for kw in PSEUDO_ENGINEERING_TITLES:
        if kw in title_lower:
            return f"Customer-facing (not engineering) role '{kw}': {opp_title}"

    if not _ENGINEERING_RE.search(title_lower):
        return f"No engineering signal in job title: {opp_title}"
    return None


def check_knockout_filters(
    company_data: EnrichedCompanyData,
    opp_title: str,
    opp_location: Optional[str],
    profile: UserProfile,
    opportunity_type: str = "job_posting",
) -> Optional[str]:
    """Check hard rejection criteria before spending LLM reasoning tokens."""
    targeting = profile.targeting

    # 0. Title Knockout (cheapest check, so it runs first)
    title_reason = check_title_relevance(opp_title, opportunity_type)
    if title_reason:
        return title_reason

    # 1. Stage Knockout
    clean_stage = company_data.stage.lower().replace("-", "_").replace(" ", "_")
    if clean_stage != "unknown" and clean_stage not in targeting.target_stages:
        return f"Stage '{company_data.stage}' not in allowed target stages {targeting.target_stages}"

    # 2. Excluded Sector Knockout
    desc_lower = f"{company_data.name} {company_data.one_liner} {opp_title}".lower()
    for sector in targeting.excluded_sectors:
        sector_keywords = sector.lower().replace("/", " ").split()
        if any(kw in desc_lower for kw in sector_keywords if len(kw) > 3):
            return f"Opportunity matches excluded sector: {sector}"

    # 3. Location Knockout (if strictly remote and posting is strictly on-site in unsupported region)
    if targeting.location.remote_only and opp_location:
        loc_lower = opp_location.lower()
        if "on-site" in loc_lower or "onsite" in loc_lower:
            if not any(r.lower() in loc_lower for r in targeting.location.prioritized_regions):
                return f"Strictly on-site role in non-prioritized location: {opp_location}"

    return None


async def score_opportunity_fit(
    company_data: EnrichedCompanyData,
    opportunity_title: str,
    opportunity_type: str,
    opportunity_location: Optional[str] = "Remote",
    raw_content: Optional[str] = None,
    profile: Optional[UserProfile] = None,
    llm_client: Optional[LLMClient] = None,
) -> FitEvaluationResult:
    """Evaluate opportunity fit score (0-100) against candidate profile."""
    user_profile = profile or load_user_profile()
    client = llm_client or LLMClient()

    # Pre-check hard knockout filters
    knockout_reason = check_knockout_filters(
        company_data, opportunity_title, opportunity_location, user_profile, opportunity_type
    )
    if knockout_reason:
        logger.info(f"Knockout triggered for {company_data.name}: {knockout_reason}")
        return FitEvaluationResult(
            fit_score=0,
            decision="DROP",
            summary_reasoning=f"Knockout filter triggered: {knockout_reason}",
            key_synergies=[],
            potential_risks=[knockout_reason],
            personalized_hook="",
            knockout_triggered=knockout_reason,
        )

    cand = user_profile.candidate
    targeting = user_profile.targeting

    prompt = f"""
You are an elite technical career advisor and talent partner. Evaluate whether this opportunity is a high-conviction match for the candidate.

=========================================
👤 CANDIDATE PROFILE
=========================================
Name: {cand.full_name}
Headline: {cand.headline}
Core Skills: {', '.join(cand.core_skills)}
Key Achievements & Proof-of-Work:
{chr(10).join('- ' + a for a in cand.key_achievements)}
Target Domains: {', '.join(targeting.target_domains)}
Target Roles: {', '.join(targeting.target_roles)}
Location Preferences: Remote only ({', '.join(targeting.location.prioritized_regions)})

=========================================
🏢 OPPORTUNITY / STARTUP TO EVALUATE
=========================================
Opportunity Type: {opportunity_type}
Title: {opportunity_title}
Company: {company_data.name} (Domain: {company_data.domain or 'N/A'}, Stage: {company_data.stage})
What they build: {company_data.one_liner}
Tech Stack: {', '.join(company_data.tech_stack) if company_data.tech_stack else 'Not specified'}
Funding / Milestone: {company_data.funding_summary or 'Early Stage'}
Location: {opportunity_location}
Raw Description / Job Details:
{raw_content or opportunity_title}

=========================================
⚖️ SCORING RUBRIC (0–100 SCALE)
=========================================
1. Domain & Mission Fit (30 pts): Does the company build in candidate's target sectors (AI infra, DevTools, distributed systems, fintech, B2B SaaS)?
2. Tech Stack & Problem Synergy (30 pts): Can the candidate's core skills directly solve their immediate technical challenges?
3. Growth & Backing Signal (25 pts): YC batch, reputable venture backers, strong founder pedigree, or high traction.
4. Stage & Remote Fit (15 pts): Sweet-spot stage (Pre-Seed to Series C), founding/early engineer scope, and remote compatibility (especially India / Global remote).

Threshold: A score >= {targeting.min_fit_score} yields decision 'PROCEED', otherwise 'DROP'.

Evaluate objectively. Provide concrete reasoning, key synergies, potential risks, and a personalized hook for outreach.
"""

    result = await client.generate_structured(
        prompt=prompt,
        response_schema=FitEvaluationResult,
        use_smart=True,
    )

    # Double-check decision against threshold
    if result.fit_score < targeting.min_fit_score:
        result.decision = "DROP"
    else:
        result.decision = "PROCEED"

    return result
