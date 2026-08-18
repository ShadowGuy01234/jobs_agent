"""Contact research node: discovers founders, verified emails, and LinkedIn profiles.

Integrates Apollo.io, Hunter.io, Tavily Search, and intelligent pattern estimation.
"""

import logging
import re
from typing import Any, Dict, Optional, Tuple
import httpx

from config import settings
from pipeline.schemas import ContactInfoResult, EnrichedCompanyData

logger = logging.getLogger(__name__)


async def query_apollo_contact(
    company_name: str,
    domain: Optional[str] = None,
    first_name: Optional[str] = None,
    last_name: Optional[str] = None,
) -> Tuple[Optional[str], Optional[str], Optional[str], str]:
    """Query Apollo.io People Match API for verified email, title, and LinkedIn URL.

    Returns: (email, title, linkedin_url, confidence)
    """
    if not settings.APOLLO_API_KEY:
        return None, None, None, "missing"

    clean_domain = (
        domain.replace("https://", "").replace("http://", "").split("/")[0].replace("www.", "")
        if domain
        else None
    )

    payload: Dict[str, Any] = {
        "api_key": settings.APOLLO_API_KEY,
        "organization_name": company_name,
    }
    if clean_domain:
        payload["domain"] = clean_domain
    if first_name:
        payload["first_name"] = first_name
    if last_name:
        payload["last_name"] = last_name

    headers = {
        "Content-Type": "application/json",
        "Cache-Control": "no-cache",
        "X-Api-Key": settings.APOLLO_API_KEY,
    }

    try:
        async with httpx.AsyncClient(timeout=12.0) as client:
            resp = await client.post(
                "https://api.apollo.io/v1/people/match",
                json=payload,
                headers=headers,
            )
            if resp.status_code == 200:
                data = resp.json()
                person = data.get("person") or {}
                email = person.get("email")
                title = person.get("title")
                linkedin_url = person.get("linkedin_url")
                email_status = person.get("email_status", "")

                if email and "extrapolated" not in email_status:
                    confidence = "verified" if email_status == "verified" else "low_confidence"
                    logger.info(f"Apollo found contact for {company_name}: {email} ({confidence})")
                    return email, title, linkedin_url, confidence
                elif email:
                    return email, title, linkedin_url, "low_confidence"
    except Exception as e:
        logger.debug(f"Apollo.io lookup error for {company_name}: {e}")

    return None, None, None, "missing"


async def query_hunter_email(
    domain: str, first_name: str, last_name: str
) -> Tuple[Optional[str], str]:
    """Query Hunter.io Email Finder API for verified email."""
    if not settings.HUNTER_API_KEY or not domain:
        return None, "missing"

    clean_domain = domain.replace("https://", "").replace("http://", "").split("/")[0].replace("www.", "")

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            url = "https://api.hunter.io/v2/email-finder"
            params = {
                "domain": clean_domain,
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
                    logger.info(f"Hunter.io found email for {clean_domain}: {email} (Score: {score})")
                    return email, confidence
    except Exception as e:
        logger.debug(f"Hunter.io lookup error for {clean_domain}: {e}")

    return None, "missing"


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


async def search_tavily_email(
    company_name: str, domain: Optional[str] = None, person_name: Optional[str] = None
) -> Tuple[Optional[str], str]:
    """Use Tavily search to discover public email addresses for the founder."""
    if not settings.TAVILY_API_KEY:
        return None, "missing"

    clean_domain = (
        domain.replace("https://", "").replace("http://", "").split("/")[0].replace("www.", "")
        if domain
        else None
    )

    query = (
        f'"{person_name}" "{company_name}" email OR contact'
        if person_name
        else f'"{company_name}" founder email OR "contact@{clean_domain or company_name}"'
    )

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.post(
                "https://api.tavily.com/search",
                json={
                    "api_key": settings.TAVILY_API_KEY,
                    "query": query,
                    "max_results": 4,
                },
            )
            if resp.status_code == 200:
                data = resp.json()
                results_text = " ".join([r.get("content", "") for r in data.get("results", [])])

                # Look for domain-matching emails first
                if clean_domain:
                    matches = re.findall(rf"\b[A-Za-z0-9._%+-]+@{re.escape(clean_domain)}\b", results_text)
                    if matches:
                        return matches[0], "low_confidence"

                # Look for general emails
                general_matches = re.findall(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b", results_text)
                for gm in general_matches:
                    if not any(excluded in gm.lower() for excluded in ["example.com", "noreply", "support", "sales", "info"]):
                        return gm, "low_confidence"
    except Exception as e:
        logger.debug(f"Tavily email search error: {e}")

    return None, "missing"


async def research_contact(
    company_data: EnrichedCompanyData,
    target_person: Optional[str] = None,
) -> ContactInfoResult:
    """Multi-tiered contact research: Apollo -> Hunter -> Tavily -> Pattern Match."""
    # 1. Determine target contact name
    name = target_person or (company_data.founders[0] if company_data.founders else None)
    if not name:
        name = "Founding Team"
        title = "Founding Team & Leadership"
    else:
        title = "Co-Founder & Leadership"

    email: Optional[str] = None
    confidence: str = "missing"
    linkedin_url: Optional[str] = None

    first_name = ""
    last_name = ""
    if name and name != "Founding Team":
        name_parts = name.split()
        first_name = name_parts[0]
        last_name = name_parts[-1] if len(name_parts) > 1 else ""

    # Tier 1: Apollo.io (People Match API)
    if settings.APOLLO_API_KEY:
        ap_email, ap_title, ap_li, ap_conf = await query_apollo_contact(
            company_name=company_data.name,
            domain=company_data.domain,
            first_name=first_name if first_name else None,
            last_name=last_name if last_name else None,
        )
        if ap_email:
            email = ap_email
            confidence = ap_conf
        if ap_title:
            title = ap_title
        if ap_li:
            linkedin_url = ap_li

    # Tier 2: Hunter.io (Email Finder API)
    if not email and settings.HUNTER_API_KEY and company_data.domain and first_name:
        h_email, h_conf = await query_hunter_email(company_data.domain, first_name, last_name)
        if h_email:
            email = h_email
            confidence = h_conf

    # Tier 3: Tavily LinkedIn Discovery (if not already found via Apollo)
    if not linkedin_url:
        linkedin_url = await find_linkedin_profile(
            company_data.name, name if name != "Founding Team" else None
        )

    # Tier 4: Tavily Email Search (if email still missing)
    if not email:
        tav_email, tav_conf = await search_tavily_email(
            company_name=company_data.name,
            domain=company_data.domain,
            person_name=name if name != "Founding Team" else None,
        )
        if tav_email:
            email = tav_email
            confidence = tav_conf

    # Tier 5: Smart Domain Pattern Matching Fallback
    if not email and company_data.domain and first_name:
        clean_domain = (
            company_data.domain.replace("https://", "")
            .replace("http://", "")
            .split("/")[0]
            .replace("www.", "")
        )
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
