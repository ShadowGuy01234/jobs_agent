"""Contact research node: discovers founders, emails, confidence scores, and LinkedIn profiles."""

import logging
import re
from typing import Optional
import httpx

from config import settings
from pipeline.schemas import ContactInfoResult, EnrichedCompanyData

logger = logging.getLogger(__name__)


async def find_linkedin_profile(
    company_name: str, person_name: Optional[str] = None
) -> Optional[str]:
    """Use Tavily to locate the founder/CTO's LinkedIn profile URL."""
    if not settings.TAVILY_API_KEY:
        return None

    query = (
        f'"{person_name}" "{company_name}" site:linkedin.com/in'
        if person_name
        else f'"{company_name}" (Founder OR CEO OR CTO) site:linkedin.com/in'
    )

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.post(
                "https://api.tavily.com/search",
                json={
                    "api_key": settings.TAVILY_API_KEY,
                    "query": query,
                    "max_results": 3,
                },
            )
            if resp.status_code == 200:
                data = resp.json()
                for result in data.get("results", []):
                    url = result.get("url", "")
                    if "linkedin.com/in/" in url:
                        return url
    except Exception as e:
        logger.debug(f"Tavily LinkedIn search error for {company_name}: {e}")

    return None


async def verify_hunter_email(domain: str, first_name: str, last_name: str) -> tuple[Optional[str], str]:
    """Query Hunter.io API for verified email."""
    if not settings.HUNTER_API_KEY or not domain:
        return None, "missing"

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            url = "https://api.hunter.io/v2/email-finder"
            params = {
                "domain": domain,
                "first_name": first_name,
                "last_name": last_name,
                "api_key": settings.HUNTER_API_KEY,
            }
            resp = await client.get(url, params=params)
            if resp.status_code == 200:
                data = resp.json().get("data", {})
                email = data.get("email")
                score = data.get("score", 0)
                if email:
                    confidence = "verified" if score >= 80 else "low_confidence"
                    return email, confidence
    except Exception as e:
        logger.debug(f"Hunter.io lookup error for {domain}: {e}")

    return None, "missing"


async def research_contact(
    company_data: EnrichedCompanyData,
    target_person: Optional[str] = None,
) -> ContactInfoResult:
    """Research target founder/executive, email, and LinkedIn profile."""
    # 1. Determine target contact name
    name = target_person or (company_data.founders[0] if company_data.founders else None)
    if not name:
        name = "Founding Team"
        title = "Founding Team & Leadership"
    else:
        title = "Co-Founder & Leadership"

    # 2. Find LinkedIn profile
    linkedin_url = await find_linkedin_profile(company_data.name, name if name != "Founding Team" else None)

    # 3. Resolve Email & Confidence
    email: Optional[str] = None
    confidence = "missing"

    # Try Hunter if domain is available and we have a person's name
    if company_data.domain and name != "Founding Team":
        name_parts = name.split()
        first_name = name_parts[0]
        last_name = name_parts[-1] if len(name_parts) > 1 else ""

        email, confidence = await verify_hunter_email(company_data.domain, first_name, last_name)

        # Fallback to smart pattern guess if Hunter is unavailable
        if not email and company_data.domain:
            clean_domain = company_data.domain.replace("https://", "").replace("http://", "").split("/")[0].replace("www.", "")
            clean_first = re.sub(r"[^a-zA-Z]", "", first_name).lower()
            if clean_first:
                email = f"{clean_first}@{clean_domain}"
                confidence = "low_confidence"

    return ContactInfoResult(
        name=name,
        title=title,
        email=email,
        email_confidence=confidence,
        linkedin_url=linkedin_url,
    )
