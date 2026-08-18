"""Contact research node: discovers founders, verified emails, and LinkedIn profiles.

Integrates contextual leadership discovery, Apollo.io, Hunter.io, Tavily Search, and intelligent email generation.
"""

import logging
import re
from typing import Any, Dict, Optional, Tuple
import httpx

from config import settings
from pipeline.schemas import ContactInfoResult, EnrichedCompanyData

logger = logging.getLogger(__name__)


def sanitize_company_name(raw_name: str) -> str:
    """Clean company names from news titles (e.g. 'Geospatial startup NeoGeo' -> 'NeoGeo')."""
    cleaned = re.sub(
        r"^(Geospatial|AI|Fintech|SaaS|Edtech|Healthtech|Deeptech|Lend-tech|E-commerce)\s+(startup|firm|platform|company)\s+",
        "",
        raw_name,
        flags=re.IGNORECASE,
    )
    cleaned = re.sub(r"\s+raises\s+.*$", "", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"\s+secures\s+.*$", "", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"\s+\(India Tech\)$", "", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"\s+\(Product Hunt Launch\)$", "", cleaned, flags=re.IGNORECASE)
    return cleaned.strip()


async def resolve_company_domain(company_name: str, context: str = "") -> Optional[str]:
    """Find the real company root domain via Tavily if missing or a news URL."""
    clean_name = sanitize_company_name(company_name)
    if not settings.TAVILY_API_KEY:
        return None

    # Extract 2-3 key words from context (e.g. 'geospatial', 'lending', etc.)
    context_words = [
        w
        for w in re.findall(r"\b[A-Za-z]{4,}\b", context)
        if w.lower()
        not in [
            "raises",
            "funding",
            "startup",
            "company",
            "million",
            "crore",
            "round",
            "series",
            "capital",
            "fund",
            "india",
            "tech",
        ]
    ]
    kw_str = " ".join(context_words[:2])
    query = f'"{clean_name}" {kw_str} official website OR startup'

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
                for r in resp.json().get("results", []):
                    url = r.get("url", "")
                    m = re.search(r"https?://(?:www\.)?([^/]+)", url)
                    if m:
                        d = m.group(1).lower()
                        if not any(
                            blocked in d
                            for blocked in [
                                "linkedin.com",
                                "twitter.com",
                                "x.com",
                                "facebook.com",
                                "yourstory.com",
                                "inc42.com",
                                "economictimes.com",
                                "entrackr.com",
                                "techcrunch.com",
                                "crunchbase.com",
                                "wikipedia.org",
                                "github.com",
                            ]
                        ):
                            return d
    except Exception as e:
        logger.debug(f"Domain resolution error for {company_name}: {e}")
    return None


async def discover_leadership_and_linkedin(
    company_name: str, domain: Optional[str] = None, context: str = ""
) -> Tuple[str, str, Optional[str]]:
    """Discover founder/CTO/GTM name, title, and verified LinkedIn URL."""
    clean_name = sanitize_company_name(company_name)
    if not settings.TAVILY_API_KEY:
        return "Founding Team", "Founding Team & Leadership", None

    context_words = [
        w
        for w in re.findall(r"\b[A-Za-z]{4,}\b", context)
        if w.lower()
        not in [
            "raises",
            "funding",
            "startup",
            "company",
            "million",
            "crore",
            "round",
            "series",
            "capital",
            "fund",
            "india",
            "tech",
        ]
    ]
    kw_str = " ".join(context_words[:2])

    query = f'"{clean_name}" {kw_str} (Founder OR CEO OR "Co-Founder" OR CTO OR "Head of Growth" OR "VP Engineering") site:linkedin.com/in'

    try:
        async with httpx.AsyncClient(timeout=12.0) as client:
            resp = await client.post(
                "https://api.tavily.com/search",
                json={
                    "api_key": settings.TAVILY_API_KEY,
                    "query": query,
                    "max_results": 5,
                },
            )
            if resp.status_code == 200:
                for r in resp.json().get("results", []):
                    title = r.get("title", "")
                    url = r.get("url", "")
                    content = r.get("content", "")

                    if "linkedin.com/in/" not in url:
                        continue

                    name_part = title.split("-")[0].split("|")[0].split("–")[0].strip()
                    # Determine specific leadership role
                    role = "Co-Founder & Leadership"
                    if "CTO" in title or "Chief Technology Officer" in title:
                        role = "Co-Founder & CTO"
                    elif "CEO" in title or "Chief Executive Officer" in title:
                        role = "Founder & CEO"
                    elif "Growth" in title or "GTM" in title:
                        role = "Head of Growth / GTM"
                    elif "Engineering" in title:
                        role = "VP / Head of Engineering"
                    elif "Founder" in title or "Co-founder" in title:
                        role = "Co-Founder"

                    # Normalize linkedin URL (clean tracking params)
                    clean_li = url.split("?")[0]
                    return name_part, role, clean_li
    except Exception as e:
        logger.debug(f"Leadership search error for {company_name}: {e}")

    return "Founding Team", "Founding Team & Leadership", None


async def query_apollo_contact(
    company_name: str,
    domain: Optional[str] = None,
    first_name: Optional[str] = None,
    last_name: Optional[str] = None,
) -> Tuple[Optional[str], Optional[str], Optional[str], str]:
    """Query Apollo.io People Match API for verified email, title, and LinkedIn URL."""
    if not settings.APOLLO_API_KEY:
        return None, None, None, "missing"

    payload: Dict[str, Any] = {
        "api_key": settings.APOLLO_API_KEY,
        "organization_name": company_name,
    }
    if domain:
        payload["domain"] = domain
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
        async with httpx.AsyncClient(timeout=10.0) as client:
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


async def search_tavily_email(
    company_name: str, domain: Optional[str] = None, person_name: Optional[str] = None
) -> Tuple[Optional[str], str]:
    """Use Tavily search to discover public email addresses for the founder."""
    if not settings.TAVILY_API_KEY:
        return None, "missing"

    query = (
        f'"{person_name}" "{domain or company_name}" email OR contact'
        if person_name
        else f'"{company_name}" founder email OR "contact@{domain or company_name}"'
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
                if domain:
                    matches = re.findall(rf"\b[A-Za-z0-9._%+-]+@{re.escape(domain)}\b", results_text)
                    if matches:
                        return matches[0], "low_confidence"

                # Look for general emails
                general_matches = re.findall(
                    r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b", results_text
                )
                for gm in general_matches:
                    if not any(
                        excluded in gm.lower()
                        for excluded in ["example.com", "noreply", "support", "sales", "info"]
                    ):
                        return gm, "low_confidence"
    except Exception as e:
        logger.debug(f"Tavily email search error: {e}")

    return None, "missing"


async def research_contact(
    company_data: EnrichedCompanyData,
    target_person: Optional[str] = None,
) -> ContactInfoResult:
    """Multi-tiered contact research: Contextual Search -> Apollo -> Hunter -> Tavily -> Smart Pattern."""
    clean_company = sanitize_company_name(company_data.name)

    # 1. Resolve domain if missing or pointing to a news site
    domain = company_data.domain
    if not domain or any(
        news in domain
        for news in [
            "yourstory.com",
            "inc42.com",
            "entrackr.com",
            "techcrunch.com",
            "producthunt.com",
            "ycombinator.com",
        ]
    ):
        resolved_domain = await resolve_company_domain(clean_company, context=company_data.one_liner or "")
        if resolved_domain:
            domain = resolved_domain
            company_data.domain = resolved_domain

    # 2. Determine target contact name, title & LinkedIn profile
    name = target_person or (company_data.founders[0] if company_data.founders else None)
    title = "Founding Team & Leadership"
    linkedin_url: Optional[str] = None

    if not name or name == "Founding Team":
        # Contextual leadership discovery via Tavily
        disc_name, disc_title, disc_li = await discover_leadership_and_linkedin(
            clean_company, domain=domain, context=company_data.one_liner or ""
        )
        name = disc_name
        title = disc_title
        linkedin_url = disc_li
    else:
        title = "Co-Founder & Leadership"

    first_name = ""
    last_name = ""
    if name and name != "Founding Team":
        name_parts = name.split()
        first_name = name_parts[0]
        last_name = name_parts[-1] if len(name_parts) > 1 else ""

    email: Optional[str] = None
    confidence: str = "missing"

    # Tier 1: Apollo.io
    if settings.APOLLO_API_KEY:
        ap_email, ap_title, ap_li, ap_conf = await query_apollo_contact(
            company_name=clean_company,
            domain=domain,
            first_name=first_name if first_name else None,
            last_name=last_name if last_name else None,
        )
        if ap_email:
            email = ap_email
            confidence = ap_conf
        if ap_title and title == "Founding Team & Leadership":
            title = ap_title
        if ap_li and not linkedin_url:
            linkedin_url = ap_li

    # Tier 2: Hunter.io
    if not email and settings.HUNTER_API_KEY and domain and first_name:
        h_email, h_conf = await query_hunter_email(domain, first_name, last_name)
        if h_email:
            email = h_email
            confidence = h_conf

    # Tier 3: Tavily Email Search
    if not email:
        tav_email, tav_conf = await search_tavily_email(
            company_name=clean_company,
            domain=domain,
            person_name=name if name != "Founding Team" else None,
        )
        if tav_email:
            email = tav_email
            confidence = tav_conf

    # Tier 4: Smart Domain Pattern Matching Fallback
    if not email and domain and first_name and first_name.lower() != "founding":
        clean_first = re.sub(r"[^a-zA-Z]", "", first_name).lower()
        clean_last = re.sub(r"[^a-zA-Z]", "", last_name).lower() if last_name else ""

        if clean_first and clean_last:
            email = f"{clean_first}.{clean_last}@{domain}"
            confidence = "low_confidence"
        elif clean_first:
            email = f"{clean_first}@{domain}"
            confidence = "low_confidence"
    elif not email and domain:
        email = f"founders@{domain}"
        confidence = "low_confidence"

    return ContactInfoResult(
        name=name,
        title=title,
        email=email,
        email_confidence=confidence,
        linkedin_url=linkedin_url,
    )
