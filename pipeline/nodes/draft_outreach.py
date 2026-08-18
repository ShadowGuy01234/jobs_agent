"""Personalized outreach drafting node supporting Founder, Stealth, Job, and Follow-up Bump pitches."""

import logging
from typing import Optional

from profile.models import UserProfile
from profile.parser import load_user_profile
from pipeline.llm import LLMClient
from pipeline.schemas import ContactInfoResult, EnrichedCompanyData, FitEvaluationResult, OutreachDraftResult

logger = logging.getLogger(__name__)


async def draft_personalized_outreach(
    company_data: EnrichedCompanyData,
    fit_eval: FitEvaluationResult,
    contact_info: ContactInfoResult,
    opportunity_type: str = "founder_reachout",
    is_follow_up: bool = False,
    original_subject: Optional[str] = None,
    profile: Optional[UserProfile] = None,
    llm_client: Optional[LLMClient] = None,
) -> OutreachDraftResult:
    """Generate high-converting, personalized cold outreach using OpenRouter Smart LLM."""
    user_profile = profile or load_user_profile()
    client = llm_client or LLMClient()
    cand = user_profile.candidate
    style = cand.writing_style

    if is_follow_up:
        # 2-sentence follow-up bump
        subject = f"Re: {original_subject or f'Building {company_data.name}'}"
        body = (
            f"Hi {contact_info.name.split()[0]},\n\n"
            f"Just bumping this in case it got buried in your inbox. "
            f"Still would love to connect for 10 mins if you're exploring early engineering help at {company_data.name}.\n\n"
            f"Best,\n"
            f"{cand.full_name} | {cand.github or cand.portfolio_url}"
        )
        return OutreachDraftResult(
            subject=subject,
            body=body,
            personalization_hook="2-sentence follow-up bump",
            word_count=len(body.split()),
        )

    prompt = f"""
You are a world-class cold outreach copywriter. Write a hyper-personalized, ultra-concise cold email from the candidate to the target founder/hiring lead.

=========================================
👤 CANDIDATE DETAILS
=========================================
Name: {cand.full_name}
Headline: {cand.headline}
Core Skills: {', '.join(cand.core_skills)}
Key Proof-of-Work:
{chr(10).join('- ' + a for a in cand.key_achievements)}
Portfolio / GitHub: {cand.github or cand.portfolio_url or ''}

=========================================
🏢 TARGET RECIPIENT & COMPANY
=========================================
Opportunity Type: {opportunity_type}
Recipient: {contact_info.name} ({contact_info.title})
Company: {company_data.name}
What they build: {company_data.one_liner}
Tech Stack: {', '.join(company_data.tech_stack) if company_data.tech_stack else 'Modern tech'}
Milestone / Funding: {company_data.funding_summary or 'Early stage'}
Personalized Hook to reference: {fit_eval.personalized_hook}
Key Technical Synergy: {fit_eval.key_synergies[0] if fit_eval.key_synergies else ''}

=========================================
✍️ STRICT WRITING RULES & CONSTRAINTS
=========================================
1. Length: STRICTLY under 120 words total.
2. Tone: {style.tone}.
3. Structure:
   - Paragraph 1: Specific reference to their recent launch, milestone, or the technical problem they're solving (using the personalized hook).
   - Paragraph 2: Candidate's relevant background + 1 concrete proof-of-work achievement with metrics that relates to their immediate engineering challenge.
   - Paragraph 3: How the candidate can help build key infrastructure/features right now.
   - Paragraph 4: Simple, low-friction CTA (e.g., 'Open to a 10-min intro chat sometime this week?').
4. Anti-Patterns to AVOID:
   {chr(10).join('- ' + ap for ap in style.anti_patterns)}
   - Never say "I hope this email finds you well" or "Sorry to bother you".
   - Do NOT use bullet points in the body.
   - Sign off naturally as:
     Best,
     {cand.full_name} | {cand.github or cand.portfolio_url or cand.linkedin}

Generate the subject line and email body.
"""

    return await client.generate_structured(
        prompt=prompt,
        response_schema=OutreachDraftResult,
        use_smart=True,
    )
