"""Direct ingestion helper for user-shared posts (WhatsApp, LinkedIn, Telegram, flyers, webhooks)."""

import base64
import hashlib
import logging
import re
from pathlib import Path
from typing import Any, Dict, Optional
from urllib.parse import urlparse

from pydantic import BaseModel, Field

from config import settings
from db.database import (
    get_opportunity_evaluation_summary,
    get_or_create_company,
    save_opportunity,
    save_or_update_contact,
)
from pipeline.llm import LLMClient
from pipeline.orchestrator import PipelineOrchestrator

logger = logging.getLogger(__name__)

_EMAIL_RE = re.compile(r"\b[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}\b")
_URL_RE = re.compile(r"https?://[^\s<>\"')]+", re.IGNORECASE)
_FREE_EMAIL_DOMAINS = {"gmail.com", "yahoo.com", "outlook.com", "hotmail.com", "proton.me", "icloud.com"}
_NON_COMPANY_HOSTS = (
    "linkedin.com",
    "t.me",
    "telegram.me",
    "whatsapp.com",
    "twitter.com",
    "x.com",
    "forms.gle",
    "docs.google.com",
    "bit.ly",
    "tinyurl.com",
    "oraclecloud.com",
    "darwinbox.in",
    "myworkdayjobs.com",
    "greenhouse.io",
    "lever.co",
    "ashbyhq.com",
    "smartrecruiters.com",
    "icims.com",
    "workable.com",
)


class SharedPostExtraction(BaseModel):
    company_name: str = Field(description="Clean company or startup name")
    domain: Optional[str] = Field(default=None, description="Company root domain e.g. mysaraswati.in")
    role_title: str = Field(description="Role or opportunity title e.g. Engineering Intern")
    opportunity_type: str = Field(
        default="job_posting",
        description="job_posting, founder_reachout, or stealth_reachout",
    )
    stage: str = Field(default="seed", description="pre_seed, seed, series_a, series_b, series_c, unknown")
    one_liner: str = Field(default="", description="1-sentence summary of what the company/role is")
    contact_name: Optional[str] = Field(default=None, description="Poster, founder, or hiring lead name if mentioned")
    contact_title: Optional[str] = Field(default=None, description="Poster role/title if known")
    contact_email: Optional[str] = Field(default=None, description="Direct email address if present in post")
    linkedin_url: Optional[str] = Field(default=None, description="LinkedIn URL from the post if any")
    apply_url: Optional[str] = Field(default=None, description="Application or company URL from the post if any")
    location: str = Field(default="India / Remote", description="Job location or Remote")
    is_remote: bool = Field(default=True)


def looks_like_job_post(text: str) -> bool:
    """Heuristic to distinguish casual chat ('hi', 'ok') from a forwarded/pasted hiring post."""
    stripped = (text or "").strip()
    if len(stripped) < 20:
        return False
    lower = stripped.lower()
    if _EMAIL_RE.search(stripped) or _URL_RE.search(stripped):
        return True
    keywords = (
        "hiring",
        "intern",
        "engineer",
        "developer",
        "apply",
        "stipend",
        "salary",
        "ctc",
        "opening",
        "role:",
        "company",
        "founder",
        "resume",
        "mail here",
    )
    return len(stripped) >= 40 and any(k in lower for k in keywords)


def _deterministic_extract_signals(text: str) -> Dict[str, Optional[str]]:
    emails = [e.lower() for e in _EMAIL_RE.findall(text)]
    urls = [u.rstrip(".,);") for u in _URL_RE.findall(text)]
    linkedin = next((u for u in urls if "linkedin.com/" in u.lower()), None)
    apply_url = next((u for u in urls if "t.me/" not in u.lower()), None)
    email = emails[0] if emails else None

    domain: Optional[str] = None
    if email:
        edom = email.split("@", 1)[1]
        if edom not in _FREE_EMAIL_DOMAINS:
            domain = edom
    if not domain:
        for u in urls:
            host = (urlparse(u).netloc or "").lower().removeprefix("www.")
            if host and not any(b in host for b in _NON_COMPANY_HOSTS):
                domain = host
                break

    return {
        "email": email,
        "linkedin_url": linkedin,
        "apply_url": apply_url,
        "domain": domain,
    }


async def extract_text_from_image_bytes(image_bytes: bytes, caption: str = "") -> str:
    """Use a vision-capable model (TokenRouter/OpenRouter) to OCR a shared hiring flyer."""
    b64 = base64.b64encode(image_bytes).decode("ascii")
    data_uri = f"data:image/jpeg;base64,{b64}"

    candidates = []
    if settings.TOKENROUTER_API_KEY and not settings.TOKENROUTER_API_KEY.startswith("your_"):
        candidates.append((settings.TOKENROUTER_BASE_URL, settings.TOKENROUTER_API_KEY, "z-ai/glm-4.6v"))
        candidates.append((settings.TOKENROUTER_BASE_URL, settings.TOKENROUTER_API_KEY, "google/gemini-3-flash-preview"))
    if settings.OPENROUTER_API_KEY and not settings.OPENROUTER_API_KEY.startswith("your_"):
        candidates.append((settings.OPENROUTER_BASE_URL, settings.OPENROUTER_API_KEY, "google/gemini-2.0-flash-001"))

    prompt = (
        "Transcribe all hiring details from this job/internship flyer image verbatim: "
        "company name, role/title, stipend/salary, skills, email address, application link, and contact person."
    )
    if caption:
        prompt += f"\n\nPost caption:\n{caption}"

    import httpx

    for base_url, api_key, model in candidates:
        try:
            async with httpx.AsyncClient(timeout=25.0) as client:
                resp = await client.post(
                    f"{base_url.rstrip('/')}/chat/completions",
                    headers={"Authorization": f"Bearer {api_key}"},
                    json={
                        "model": model,
                        "messages": [
                            {
                                "role": "user",
                                "content": [
                                    {"type": "text", "text": prompt},
                                    {"type": "image_url", "image_url": {"url": data_uri}},
                                ],
                            }
                        ],
                        "max_tokens": 500,
                    },
                )
                if resp.status_code == 200:
                    text = (
                        resp.json()
                        .get("choices", [{}])[0]
                        .get("message", {})
                        .get("content", "")
                        .strip()
                    )
                    if text:
                        return f"{caption}\n\n[Extracted from flyer image]\n{text}".strip() if caption else text
        except Exception as e:
            logger.debug(f"Vision extraction failed on {model}: {e}")

    return caption


async def parse_shared_post(text: str, llm_client: Optional[LLMClient] = None) -> SharedPostExtraction:
    """Extract structured company/role/contact details from a shared WhatsApp/Telegram/LinkedIn post."""
    signals = _deterministic_extract_signals(text)
    client = llm_client or LLMClient()

    prompt = f"""
Extract structured startup/job outreach details from this user-forwarded hiring post.

POST TEXT:
{text[:3000]}

Instructions:
1. Extract the clean company name and role title.
2. Extract domain (root domain like mysaraswati.in — infer from company email domain or official website if present, NOT linkedin.com/t.me).
3. Extract any contact_name (e.g. poster or founder name like 'Alok Singh'), contact_email, and linkedin_url verbatim if present.
4. Set opportunity_type to 'job_posting' if hiring for a role/internship, or 'founder_reachout' if a general startup launch.
5. Set stage to 'seed' for early startups if unknown, or 'unknown' if unclear.
"""
    try:
        parsed = await client.generate_structured(
            prompt=prompt,
            response_schema=SharedPostExtraction,
            use_smart=False,
        )
    except Exception as e:
        logger.warning(f"LLM shared post extraction fallback: {e}")
        first_line = text.strip().splitlines()[0][:80] if text.strip() else "Shared Opportunity"
        parsed = SharedPostExtraction(
            company_name=signals["domain"].split(".")[0].capitalize() if signals["domain"] else first_line[:40],
            role_title=first_line,
            one_liner=text[:200],
        )

    parsed.contact_email = parsed.contact_email or signals["email"]
    parsed.linkedin_url = parsed.linkedin_url or signals["linkedin_url"]
    parsed.apply_url = parsed.apply_url or signals["apply_url"]
    parsed.domain = parsed.domain or signals["domain"]
    if parsed.opportunity_type not in ("job_posting", "founder_reachout", "stealth_reachout"):
        parsed.opportunity_type = "job_posting"
    return parsed


async def ingest_and_process_shared_post(
    text: str,
    source_url: Optional[str] = None,
    orchestrator: Optional[PipelineOrchestrator] = None,
    db_path: Optional[Path] = None,
    llm_client: Optional[LLMClient] = None,
) -> Dict[str, Any]:
    """Ingest a user-shared post into SQLite, pre-seed extracted contacts, and run LangGraph."""
    parsed = await parse_shared_post(text, llm_client=llm_client)
    target_db = Path(db_path) if db_path else settings.DATABASE_PATH

    company_id = get_or_create_company(
        domain=parsed.domain,
        name=parsed.company_name,
        website=f"https://{parsed.domain}" if parsed.domain else parsed.apply_url,
        stage=parsed.stage,
        source="shared_post",
        description=parsed.one_liner or text[:300],
        country=parsed.location,
        db_path=target_db,
    )

    canonical_url = (
        source_url
        or parsed.apply_url
        or f"tg_manual://{hashlib.sha1(text.strip().encode('utf-8')).hexdigest()[:16]}"
    )

    opp_id = save_opportunity(
        company_id=company_id,
        type_=parsed.opportunity_type,
        title=parsed.role_title,
        url=canonical_url,
        location=parsed.location,
        is_remote=parsed.is_remote,
        raw_content=text[:4000],
        status="discovered",
        db_path=target_db,
    )

    if opp_id is None:
        return {
            "duplicate": True,
            "parsed": parsed.model_dump(),
            "opportunity_id": None,
            "interrupt_payload": None,
            "evaluation": None,
        }

    # Pre-seed extracted verified email so node_research skips Hunter/Tavily/LLM!
    if parsed.contact_email:
        save_or_update_contact(
            company_id=company_id,
            name=parsed.contact_name or "Hiring Team",
            title=parsed.contact_title or "Hiring Lead",
            email=parsed.contact_email,
            email_confidence="verified",
            linkedin_url=parsed.linkedin_url,
            source="shared_post",
            db_path=target_db,
        )

    owns_orch = orchestrator is None
    orch = orchestrator or PipelineOrchestrator(db_path=target_db)
    try:
        interrupt_payload = await orch.process_opportunity(opp_id)
    finally:
        if owns_orch:
            await orch.close()

    summary = get_opportunity_evaluation_summary(opp_id, db_path=target_db)
    return {
        "duplicate": False,
        "parsed": parsed.model_dump(),
        "opportunity_id": opp_id,
        "interrupt_payload": interrupt_payload,
        "evaluation": summary,
    }
