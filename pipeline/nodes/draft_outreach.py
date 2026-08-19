"""Personalized outreach drafting node powered by the Remote Job Message Blueprint.

Implements the 3-Layer Cold Outreach Architecture (by bhipakshi):
- Layer 1: Proof of Attention (Builds trust through specific craft/product recognition)
- Layer 2: Narrative Alignment (Builds fit via a concise converging career thread)
- Layer 3: The Anti-Ask (Builds curiosity with a low-stakes, pressure-free 15-min chat)
"""

import logging
from typing import Optional

from profile.models import UserProfile
from profile.parser import load_user_profile
from pipeline.llm import LLMClient
from pipeline.schemas import (
    ContactInfoResult,
    EnrichedCompanyData,
    FitEvaluationResult,
    OutreachDraftResult,
)

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
    """Generate high-converting personalized cold outreach using the 3-Layer Blueprint."""
    user_profile = profile or load_user_profile()
    client = llm_client or LLMClient()
    cand = user_profile.candidate
    style = cand.writing_style

    first_name = contact_info.name.split()[0] if contact_info.name and contact_info.name != "Founding Team" else "there"

    # 1. Handle Follow-Up Bump
    if is_follow_up:
        subject = f"Re: {original_subject or f'Quick note on {company_data.name}'}"
        body = (
            f"Hi {first_name},\n\n"
            f"Just bumping this in case it got buried in your inbox. "
            f"Still following your work on {company_data.name} and would love to grab a quick 10-15 min chat if you're open to it.\n\n"
            f"Best,\n"
            f"{cand.full_name} | {cand.github or cand.portfolio_url}"
        )
        return OutreachDraftResult(
            subject=subject,
            body=body,
            personalization_hook="2-sentence follow-up bump",
            word_count=len(body.split()),
        )

    # 2. Build 3-Layer Blueprint Prompt
    primary_achievement = cand.key_achievements[0] if cand.key_achievements else "scaling high-performance software systems"
    secondary_achievement = cand.key_achievements[1] if len(cand.key_achievements) > 1 else cand.headline

    prompt = f"""
You are an elite cold outreach copywriter applying "THE REMOTE JOB MESSAGE BLUEPRINT" (3-Layer Cold Outreach Framework).

Draft a hyper-personalized, high-converting cold email from the candidate to the target founder/hiring lead.

=========================================
👤 CANDIDATE PROFILE
=========================================
Name: {cand.full_name}
Headline: {cand.headline}
Core Skills: {', '.join(cand.core_skills)}
Current Focus / Recent Achievement: {primary_achievement}
Past Experience / Proof of Work: {secondary_achievement}
Portfolio / GitHub: {cand.github or cand.portfolio_url or ''}

=========================================
🏢 TARGET RECIPIENT & COMPANY
=========================================
Recipient: {first_name} ({contact_info.title})
Company: {company_data.name}
Domain: {company_data.domain or 'startup'}
What they build / Product: {company_data.one_liner}
Tech Stack: {', '.join(company_data.tech_stack) if company_data.tech_stack else 'Modern tech'}
Milestone / Context: {company_data.funding_summary or 'Early Stage'}
Personalized Craft Hook: {fit_eval.personalized_hook}
Key Technical Synergy: {fit_eval.key_synergies[0] if fit_eval.key_synergies else 'distributed systems & AI agent workflows'}

=========================================
📐 THE 3-LAYER MESSAGE BLUEPRINT
=========================================
Follow this EXACT sequence and psychology:

1. SUBJECT LINE:
   - Format: "Quick note on [specific work/feature/launch of theirs]"
   - Examples: "Quick note on machine0 VM orchestration", "Quick note on your geospatial data pipeline"

2. LAYER 1: PROOF OF ATTENTION (Builds Trust - ~35 words)
   - Mention one specific piece of their craft, product launch, or architectural approach (using the Personalized Craft Hook).
   - Compliment their CRAFT and engineering work, NOT generic mission fluff.

3. LAYER 2: NARRATIVE ALIGNMENT (Builds Fit - ~45 words)
   - Use this narrative structure:
     "Right now I am [what candidate is building/focusing on]. Before that I [relevant concrete experience with metric/proof]. What drew me to your work is [specific connection to company's challenge/product]."
   - Frame the candidate's career path as naturally converging toward what this startup is doing.

4. LAYER 3: THE ANTI-ASK (Builds Curiosity & Removes Pressure - ~30 words)
   - Propose a low-stakes, time-bounded 15-minute call.
   - Explicitly remove the pressure: "Openings or not, I am genuinely curious about [specific technical topic/scaling challenge]."
   - Suggest a specific time window: "Would Tuesday or Thursday afternoon work for a quick call?"

5. SIGN-OFF:
   Best,
   {cand.full_name}
   {cand.github or cand.portfolio_url or ''}

=========================================
🚫 CRITICAL ANTI-PATTERNS (DO NOT DO)
=========================================
- Total length MUST be between 90 and 140 words.
- Never use generic openers like "I hope this email finds you well" or "I am writing to apply for...".
- Never ask directly for a job or say "Are you hiring?". Ask for a conversation ("openings or not").
- No bullet points. Use clean, human paragraphs.
- Tone: Confident, curious peer; respectful of their time.
"""

    return await client.generate_structured(
        prompt=prompt,
        response_schema=OutreachDraftResult,
        use_smart=True,
    )
