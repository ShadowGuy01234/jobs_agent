"""Personalized outreach drafting node powered by the Remote Job Message Blueprint.

Implements the 3-Layer Cold Outreach Architecture (by bhipakshi):
- Layer 1: Proof of Attention (Builds trust through specific craft/product recognition)
- Layer 2: Narrative Alignment (Builds fit via a concise converging career thread)
- Layer 3: The Anti-Ask (Builds curiosity with a low-stakes, pressure-free chat)

The Layer 3 scheduling ask is date-aware: the two days offered are computed from the current
date (pipeline/timeslots.py) rather than hardcoded, so drafts never propose a day that has
already passed or repeat the same pair on every send.
"""

import logging
from typing import Optional

from profile.models import UserProfile
from profile.parser import load_user_profile
from pipeline.llm import LLMClient
from pipeline.timeslots import next_business_days, today_context
from pipeline.schemas import (
    ContactInfoResult,
    EnrichedCompanyData,
    FitEvaluationResult,
    OutreachDraftResult,
)

logger = logging.getLogger(__name__)

COPYWRITER_SYSTEM_PROMPT = (
    "You are an elite cold-outreach copywriter who writes short, specific, peer-to-peer emails "
    "from engineers to startup founders. You write like a curious human, never like a recruiter "
    "or an applicant. Always return strictly valid JSON conforming exactly to the requested JSON "
    "schema. Do not include any conversational preamble or markdown code fence; output raw JSON."
)


def _scheduling_ask(style) -> tuple[str, str]:
    """Build the date-aware scheduling sentence and a matching anti-repetition guard."""
    days = next_business_days(tz=style.timezone)
    day_phrase = " or ".join(days)
    ask = (
        f"{day_phrase}, {style.meeting_window} {style.timezone_label}"
        if style.meeting_window
        else day_phrase
    )
    return ask, day_phrase


async def draft_personalized_outreach(
    company_data: EnrichedCompanyData,
    fit_eval: FitEvaluationResult,
    contact_info: ContactInfoResult,
    opportunity_type: str = "founder_reachout",
    opportunity_title: Optional[str] = None,
    raw_content: Optional[str] = None,
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
    ask, day_phrase = _scheduling_ask(style)

    # 1. Handle Follow-Up Bump
    if is_follow_up:
        subject = f"Re: {original_subject or f'Quick note on {company_data.name}'}"
        body = (
            f"Hi {first_name},\n\n"
            f"Just bumping this in case it got buried in your inbox. "
            f"Still following your work on {company_data.name} and would love to grab a quick "
            f"{style.meeting_minutes} min chat if you're open to it — {ask} works on my end.\n\n"
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
    achievements = "\n".join(f"- {a}" for a in cand.key_achievements) or "- Scaling high-performance software systems"
    profile_anti_patterns = "\n".join(f"- {p}" for p in style.anti_patterns)
    role_context = f"Role They Posted: {opportunity_title}" if opportunity_title else ""
    if raw_content:
        role_context += f"\nRole Details (excerpt): {raw_content[:800]}"

    prompt = f"""
You are an elite cold outreach copywriter applying "THE REMOTE JOB MESSAGE BLUEPRINT" (3-Layer Cold Outreach Framework).

Draft a hyper-personalized, high-converting cold email from the candidate to the target founder/hiring lead.

=========================================
📅 CURRENT DATE CONTEXT
=========================================
Today is {today_context(tz=style.timezone)}.
The ONLY days you may offer for a call are: {day_phrase}.
The candidate is based in {style.timezone_label} and will state that timezone explicitly.

=========================================
👤 CANDIDATE PROFILE
=========================================
Name: {cand.full_name}
Headline: {cand.headline}
Core Skills: {', '.join(cand.core_skills)}
Portfolio / GitHub: {cand.github or cand.portfolio_url or ''}

Proof-of-Work Achievements (SELECT THE 1-2 MOST RELEVANT to this specific company — do not use all of them, and do not default to the first two):
{achievements}

=========================================
🏢 TARGET RECIPIENT & COMPANY
=========================================
Recipient: {first_name} ({contact_info.title})
Company: {company_data.name}
Domain: {company_data.domain or 'startup'}
Outreach Context: {opportunity_type}
{role_context}
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
   - Pick the achievement that best matches THEIR technical problem. A vision-AI win is the wrong proof for a payments infra company.

4. LAYER 3: THE ANTI-ASK (Builds Curiosity & Removes Pressure - ~30 words)
   - Propose a low-stakes, time-bounded {style.meeting_minutes}-minute call.
   - Explicitly remove the pressure: "Openings or not, I am genuinely curious about [specific technical topic/scaling challenge]."
   - Offer EXACTLY this availability, verbatim: "{ask}".

5. SIGN-OFF:
   Best,
   {cand.full_name}
   {cand.github or cand.portfolio_url or ''}

=========================================
🚫 CRITICAL ANTI-PATTERNS (DO NOT DO)
=========================================
- Total body length MUST be at most {style.max_words} words.
- Do NOT name any day of the week other than: {day_phrase}. Never write "Tuesday or Thursday" out of habit.
- Do NOT invent a calendar date, a specific clock time, or a timezone other than {style.timezone_label}.
- Never use generic openers like "I hope this email finds you well" or "I am writing to apply for...".
- Never ask directly for a job or say "Are you hiring?". Ask for a conversation ("openings or not").
- No bullet points. Use clean, human paragraphs.
- Tone: {style.tone}. Confident, curious peer; respectful of their time.
{profile_anti_patterns}
"""

    return await client.generate_structured(
        prompt=prompt,
        response_schema=OutreachDraftResult,
        use_smart=True,
        system_prompt=COPYWRITER_SYSTEM_PROMPT,
    )
