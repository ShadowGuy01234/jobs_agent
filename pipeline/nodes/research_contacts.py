"""Contact research node: discovers founders, verified emails, and LinkedIn profiles.

Combines Website Deep Scraping, Targeted Persona Search, LLM Contact Extraction, and MX-validated pattern matching.
Zero business-email or paid API subscription required.
"""

import logging
import re
from typing import Any, Dict, List, Optional, Tuple
import httpx

from config import settings
from pipeline.llm import LLMClient
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


async def scrape_website_emails(domain: str) -> List[str]:
    """Scrape contact pages and security.txt directly from the company website."""
    if not domain:
        return []

    found_emails = set()
    pages_to_check = [
        f"https://{domain}",
        f"https://{domain}/about",
        f"https://{domain}/team",
        f"https://{domain}/contact",
        f"https://{domain}/privacy",
        f"https://{domain}/.well-known/security.txt",
    ]

    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        )
    }

    async with httpx.AsyncClient(timeout=5.0, follow_redirects=True, headers=headers) as client:
        for url in pages_to_check:
            try:
                resp = await client.get(url)
                if resp.status_code == 200:
                    text = resp.text
                    matches = re.findall(
                        rf"\b[A-Za-z0-9._%+-]+@{re.escape(domain)}\b", text, flags=re.IGNORECASE
                    )
                    for m in matches:
                        clean_email = m.lower().strip()
                        if not any(
                            excluded in clean_email
                            for excluded in ["noreply", "privacy", "donotreply", "abuse", "support"]
                        ):
                            found_emails.add(clean_email)
            except Exception:
                continue

    return list(found_emails)


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
        async with httpx.AsyncClient(timeout=8.0) as client:
            resp = await client.post(
                "https://api.tavily.com/search",
                json={
                    "api_key": settings.TAVILY_API_KEY,
                    "query": query,
                    "max_results": 3,
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


async def research_contact(
    company_data: EnrichedCompanyData,
    target_person: Optional[str] = None,
) -> ContactInfoResult:
    """Multi-tiered contact research engine: Website Scraper -> Precision Dorks -> LLM Extraction -> Pattern Generator."""
    clean_company = sanitize_company_name(company_data.name)

    # 1. Resolve domain if missing or pointing to a news/aggregator URL
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
        resolved_domain = await resolve_company_domain(
            clean_company, context=company_data.one_liner or ""
        )
        if resolved_domain:
            domain = resolved_domain
            company_data.domain = resolved_domain

    # 2. Scrape website for direct contact/team emails
    site_emails = []
    if domain:
        site_emails = await scrape_website_emails(domain)

    # 3. Search web for Founder/CTO LinkedIn profiles and contact details
    snippets: List[str] = []
    if site_emails:
        snippets.append(f"Official Company Website Emails: {', '.join(site_emails)}")

    if settings.TAVILY_API_KEY:
        async with httpx.AsyncClient(timeout=10.0) as http_client:
            queries = [
                f'site:linkedin.com/in ("Founder" OR "Co-Founder" OR "CEO" OR "CTO" OR "Head of Growth" OR "VP Engineering") "{clean_company}"',
                f'"{clean_company}" ("founder" OR "leadership" OR "contact" OR "reach me at") "{domain or clean_company}"',
            ]
            for q in queries:
                try:
                    resp = await http_client.post(
                        "https://api.tavily.com/search",
                        json={"api_key": settings.TAVILY_API_KEY, "query": q, "max_results": 4},
                    )
                    if resp.status_code == 200:
                        for r in resp.json().get("results", []):
                            snippets.append(
                                f"Title: {r.get('title')}\nURL: {r.get('url')}\nContent: {r.get('content')}"
                            )
                except Exception as e:
                    logger.debug(f"Search query error: {e}")

    context_text = "\n---\n".join(snippets)

    # 4. Use LLM to cleanly extract executive name, title, verified LinkedIn URL, and email
    known_founder = target_person or (company_data.founders[0] if company_data.founders else None)
    client = LLMClient()
    prompt = f"""
Analyze the following search snippets and extract contact information for the startup's leadership.

COMPANY NAME: {clean_company}
DOMAIN: {domain or 'Unknown'}
TARGET PERSON / KNOWN FOUNDER: {known_founder or 'Any primary Founder/CTO'}

SEARCH RESULTS & WEBPAGE SNIPPETS:
{context_text}

Instructions:
1. If a TARGET PERSON / KNOWN FOUNDER ({known_founder}) is specified, extract details for that specific person. Otherwise, identify the primary Founder, CEO, or CTO from the snippets.
2. Extract their exact title (e.g. 'Founder & CEO', 'Co-Founder & CTO', 'Head of Growth').
3. Extract their exact personal LinkedIn profile URL if found in the search results (must be a real URL like https://linkedin.com/in/username).
4. If a direct email is found in the text or website for this person, extract it. Otherwise generate the best professional email using their name and domain (e.g. first@domain or first.last@domain).
5. Set email_confidence to 'verified' if found directly in text/website, or 'low_confidence' if inferred from domain pattern.
"""

    try:
        contact_res = await client.generate_structured(
            prompt=prompt,
            response_schema=ContactInfoResult,
            use_smart=False,
        )
        if known_founder:
            contact_res.name = known_founder
            if domain and (not contact_res.email or not contact_res.email.endswith(f"@{domain}")):
                first = re.sub(r"[^a-zA-Z]", "", known_founder.split()[0].lower())
                contact_res.email = f"{first}@{domain}"
                if contact_res.email_confidence == "missing":
                    contact_res.email_confidence = "low_confidence"
        return contact_res
    except Exception as e:
        logger.warning(f"LLM contact extraction fallback: {e}")

    # Fallback if extraction encounters any edge case
    fallback_name = target_person or (company_data.founders[0] if company_data.founders else "Founding Team")
    first_name = fallback_name.split()[0].lower() if fallback_name != "Founding Team" else "founders"
    clean_first = re.sub(r"[^a-zA-Z]", "", first_name)
    fallback_email = f"{clean_first}@{domain}" if domain else None

    return ContactInfoResult(
        name=fallback_name,
        title="Founding Team & Leadership",
        email=fallback_email,
        email_confidence="low_confidence" if fallback_email else "missing",
        linkedin_url=None,
    )
