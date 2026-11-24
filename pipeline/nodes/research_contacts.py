"""Contact research node: discovers founders, verified emails, and LinkedIn profiles.

Multi-tier waterfall (each tier only runs if the previous one didn't produce a confident hit):
  1. Hunter.io Domain Search & Email Finder (primary when HUNTER_API_KEY is set).
  2. Website scraping (concurrent contact/team/careers pages + mailto: links + light de-obfuscation).
  3. Tavily search + LLM extraction - finds the name/title/LinkedIn, and any email mentioned in text,
     followed by a targeted Hunter.io Email Finder lookup for the extracted person.
  4. Apollo.io person match (if APOLLO_API_KEY set and valid) - looks up a verified email for a named person.
  5. Pattern-guessing, ranked by which guess formats have actually gotten replies before, and
     each candidate is probed with a real (zero-cost) MX + SMTP RCPT TO check before being trusted.
  6. Role-based inbox fallback (careers@, hello@, etc.) - only kept if the SMTP probe confirms it.
"""

import asyncio
import logging
import re
from typing import Any, Dict, List, Optional, Tuple
import httpx

from config import settings
from pipeline.email_verify import verify_email_smtp
from pipeline.llm import LLMClient
from pipeline.schemas import ContactInfoResult, EnrichedCompanyData

logger = logging.getLogger(__name__)

_hunter_disabled = False
_apollo_disabled = False

LEADERSHIP_TITLES = (
    "founder",
    "co-founder",
    "ceo",
    "cto",
    "coo",
    "head of",
    "vp ",
    "vice president",
    "director",
)

ENG_LEADERSHIP_TITLES = (
    "cto",
    "vp engineering",
    "vp of engineering",
    "head of engineering",
    "engineering manager",
    "director of engineering",
    "head of ai",
    "tech lead",
    "engineering",
)

ROLE_BASED_INBOXES = ["careers", "talent", "hello", "team", "jobs", "founders"]


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


def _deobfuscate(text: str) -> str:
    """Undo common human-readable email obfuscation before regex extraction."""
    out = re.sub(r"\s*[\[\(]\s*at\s*[\]\)]\s*", "@", text, flags=re.IGNORECASE)
    out = re.sub(r"\s+at\s+", "@", out, flags=re.IGNORECASE)
    out = re.sub(r"\s*[\[\(]\s*dot\s*[\]\)]\s*", ".", out, flags=re.IGNORECASE)
    out = re.sub(r"\s+dot\s+", ".", out, flags=re.IGNORECASE)
    return out


async def scrape_website_emails(domain: str) -> List[str]:
    """Scrape contact/team/careers pages and security.txt directly from the company website."""
    if not domain:
        return []

    found_emails = set()
    pages_to_check = [
        f"https://{domain}",
        f"https://{domain}/about",
        f"https://{domain}/about-us",
        f"https://{domain}/team",
        f"https://{domain}/leadership",
        f"https://{domain}/founders",
        f"https://{domain}/contact",
        f"https://{domain}/contact-us",
        f"https://{domain}/careers",
        f"https://{domain}/jobs",
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
        sem = asyncio.Semaphore(6)

        async def _fetch_page(url: str) -> List[str]:
            async with sem:
                try:
                    resp = await client.get(url)
                    if resp.status_code != 200:
                        return []
                    text = resp.text
                    mailto_matches = re.findall(
                        r'mailto:([A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+)', text, flags=re.IGNORECASE
                    )
                    plain_matches = re.findall(
                        rf"\b[A-Za-z0-9._%+-]+@{re.escape(domain)}\b", text, flags=re.IGNORECASE
                    )
                    deobfuscated_matches = re.findall(
                        rf"\b[A-Za-z0-9._%+-]+@{re.escape(domain)}\b",
                        _deobfuscate(text),
                        flags=re.IGNORECASE,
                    )
                    emails: List[str] = []
                    for m in [*mailto_matches, *plain_matches, *deobfuscated_matches]:
                        clean_email = m.lower().strip()
                        if clean_email.endswith(f"@{domain}") and not any(
                            excluded in clean_email
                            for excluded in ["noreply", "privacy", "donotreply", "abuse", "support"]
                        ):
                            emails.append(clean_email)
                    return emails
                except Exception:
                    return []

        results = await asyncio.gather(*(_fetch_page(u) for u in pages_to_check))
        for page_emails in results:
            found_emails.update(page_emails)

    return list(found_emails)


async def lookup_hunter_domain_search(domain: str) -> List[Dict[str, Any]]:
    """Query Hunter.io domain-search for real (crawled/verified) emails at this domain."""
    global _hunter_disabled
    if _hunter_disabled or not settings.HUNTER_API_KEY or not domain:
        return []
    try:
        async with httpx.AsyncClient(timeout=8.0) as client:
            resp = await client.get(
                "https://api.hunter.io/v2/domain-search",
                headers={"X-API-KEY": settings.HUNTER_API_KEY},
                params={"domain": domain, "limit": 10, "type": "personal"},
            )
            if resp.status_code == 200:
                return resp.json().get("data", {}).get("emails", [])
            if resp.status_code in (401, 402):
                _hunter_disabled = True
                logger.warning(f"Hunter.io disabled after HTTP {resp.status_code} on domain-search.")
            else:
                logger.debug(f"Hunter domain search returned HTTP {resp.status_code} for {domain}")
    except Exception as e:
        logger.debug(f"Hunter domain search error for {domain}: {e}")
    return []


async def lookup_hunter_email_finder(domain: str, person_name: Optional[str]) -> Optional[Dict[str, Any]]:
    """Query Hunter.io /v2/email-finder for a verified email of a named person at a domain."""
    global _hunter_disabled
    if _hunter_disabled or not settings.HUNTER_API_KEY or not domain or not person_name:
        return None
    name_parts = [p for p in person_name.strip().split() if p]
    if len(name_parts) < 2:
        return None
    try:
        async with httpx.AsyncClient(timeout=8.0) as client:
            resp = await client.get(
                "https://api.hunter.io/v2/email-finder",
                headers={"X-API-KEY": settings.HUNTER_API_KEY},
                params={
                    "domain": domain,
                    "first_name": name_parts[0],
                    "last_name": name_parts[-1],
                },
            )
            if resp.status_code == 200:
                data = resp.json().get("data") or {}
                if data.get("email"):
                    return data
            elif resp.status_code in (401, 402):
                _hunter_disabled = True
                logger.warning(f"Hunter.io disabled after HTTP {resp.status_code} on email-finder.")
            else:
                logger.debug(f"Hunter email-finder returned HTTP {resp.status_code} for {person_name}@{domain}")
    except Exception as e:
        logger.debug(f"Hunter email-finder error for {person_name}@{domain}: {e}")
    return None


def _pick_best_hunter_contact(
    hunter_emails: List[Dict[str, Any]],
    target_person: Optional[str] = None,
    opportunity_type: str = "founder_reachout",
) -> Optional[ContactInfoResult]:
    """Select the strongest personal/leadership contact from Hunter domain-search results."""
    if not hunter_emails:
        return None

    target_lower = (target_person or "").strip().lower()
    is_job_posting = opportunity_type == "job_posting"
    best_score = -1
    best_entry: Optional[Dict[str, Any]] = None

    for entry in hunter_emails:
        email = (entry.get("value") or "").strip().lower()
        if not email or entry.get("type") == "generic":
            continue

        first = (entry.get("first_name") or "").strip()
        last = (entry.get("last_name") or "").strip()
        full_name = f"{first} {last}".strip()
        position = (entry.get("position") or "").strip()
        pos_lower = position.lower()
        confidence = int(entry.get("confidence") or 0)
        ver_status = ((entry.get("verification") or {}).get("status") or "").lower()

        if confidence < 65 and ver_status != "valid":
            continue

        score = confidence
        if ver_status == "valid":
            score += 25
        elif ver_status == "invalid":
            continue

        if target_lower and full_name and target_lower in full_name.lower():
            score += 120
        if any(title in pos_lower for title in LEADERSHIP_TITLES):
            score += 60
        if is_job_posting and any(title in pos_lower for title in ENG_LEADERSHIP_TITLES):
            score += 45
        elif not is_job_posting and any(t in pos_lower for t in ("founder", "co-founder", "ceo", "cto")):
            score += 30
        if (entry.get("seniority") or "").lower() == "executive":
            score += 35
        if (entry.get("department") or "").lower() in ("executive", "it", "management"):
            score += 15
        if full_name:
            score += 10

        if score > best_score:
            best_score = score
            best_entry = entry

    if not best_entry:
        return None

    first = (best_entry.get("first_name") or "").strip()
    last = (best_entry.get("last_name") or "").strip()
    full_name = f"{first} {last}".strip() or "Founding Team"
    position = (best_entry.get("position") or "").strip() or "Founding Team & Leadership"
    return ContactInfoResult(
        name=full_name,
        title=position,
        email=best_entry["value"].strip().lower(),
        email_confidence="verified",
        linkedin_url=best_entry.get("linkedin"),
        twitter_url=best_entry.get("twitter"),
    )


async def lookup_apollo_person(domain: str, person_name: Optional[str]) -> Optional[Dict[str, Any]]:
    """Query Apollo.io's people/match endpoint for a verified email of a named person at a domain.

    Requires a name (Apollo won't reveal an email off a bare domain). Silently returns None if
    no APOLLO_API_KEY is configured, no name is known, or the call fails/is rejected.
    """
    global _apollo_disabled
    if _apollo_disabled or not settings.APOLLO_API_KEY or not domain or not person_name:
        return None
    name_parts = person_name.strip().split()
    if not name_parts:
        return None
    try:
        async with httpx.AsyncClient(timeout=8.0) as client:
            resp = await client.post(
                "https://api.apollo.io/v1/people/match",
                headers={"Content-Type": "application/json", "x-api-key": settings.APOLLO_API_KEY},
                json={
                    "api_key": settings.APOLLO_API_KEY,
                    "first_name": name_parts[0],
                    "last_name": name_parts[-1] if len(name_parts) > 1 else "",
                    "domain": domain,
                    "reveal_personal_emails": False,
                },
            )
            if resp.status_code == 200:
                person = resp.json().get("person")
                if person and person.get("email") and "email_not_unlocked" not in str(person.get("email")):
                    return person
            elif resp.status_code in (401, 403):
                _apollo_disabled = True
                logger.warning(f"Apollo.io disabled after HTTP {resp.status_code} (invalid/unauthorized key).")
            else:
                logger.debug(f"Apollo people/match returned HTTP {resp.status_code} for {person_name}@{domain}")
    except Exception as e:
        logger.debug(f"Apollo lookup error for {person_name}@{domain}: {e}")
    return None


def _generate_pattern_candidates(first: str, last: Optional[str], domain: str) -> List[Tuple[str, str]]:
    """Return [(pattern_type, candidate_email), ...] for the standard corporate email formats."""
    first = re.sub(r"[^a-zA-Z]", "", first).lower()
    last = re.sub(r"[^a-zA-Z]", "", last).lower() if last else ""
    if not first or not domain:
        return []
    candidates = [("first", f"{first}@{domain}")]
    if last:
        candidates += [
            ("first.last", f"{first}.{last}@{domain}"),
            ("firstlast", f"{first}{last}@{domain}"),
            ("first_last", f"{first}_{last}@{domain}"),
            ("flast", f"{first[0]}{last}@{domain}"),
        ]
    return candidates


async def _best_guessed_email(
    first: str, last: Optional[str], domain: str, pattern_success_rates: Optional[Dict[str, float]] = None
) -> Tuple[Optional[str], Optional[str], str]:
    """Rank pattern candidates by historical success rate, probe each via SMTP, and return the
    best (email, pattern_type, confidence) triple. confidence is 'verified' if the mail server
    explicitly accepted it, 'low_confidence' if inconclusive (probe blocked/timeout/catch-all),
    or ('missing' / None / None / 'missing') if every candidate was explicitly rejected."""
    candidates = _generate_pattern_candidates(first, last, domain)
    if not candidates:
        return None, None, "missing"

    rates = pattern_success_rates or {}
    candidates.sort(key=lambda c: rates.get(c[0], 0.5), reverse=True)

    best_unknown: Optional[Tuple[str, str]] = None
    any_valid_syntax = False
    for pattern_type, email in candidates:
        result = await asyncio.to_thread(verify_email_smtp, email)
        if result == "verified":
            return email, pattern_type, "verified"
        if result == "unknown":
            any_valid_syntax = True
            if best_unknown is None:
                best_unknown = (pattern_type, email)
        # "invalid" -> skip this candidate entirely

    if best_unknown:
        return best_unknown[1], best_unknown[0], "low_confidence"
    if any_valid_syntax:
        return None, None, "missing"
    # Every candidate was explicitly rejected by the mail server - fall back to the
    # highest-ranked guess rather than giving up entirely, but mark it clearly unverified.
    pattern_type, email = candidates[0]
    return email, pattern_type, "low_confidence"


async def _find_role_based_inbox(domain: str) -> Optional[str]:
    """Last-resort fallback: only return a generic inbox (careers@, hello@, ...) if the SMTP
    probe actively confirms it exists - an unverified generic guess is worse than nothing."""
    for local_part in ROLE_BASED_INBOXES:
        candidate = f"{local_part}@{domain}"
        result = await asyncio.to_thread(verify_email_smtp, candidate)
        if result == "verified":
            return candidate
    return None


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
    pattern_success_rates: Optional[Dict[str, float]] = None,
    opportunity_type: str = "founder_reachout",
) -> ContactInfoResult:
    """Multi-tiered contact research engine: Hunter.io (Primary) -> Website Scraper ->
    Precision Dorks + LLM Extraction -> Hunter Email Finder -> Apollo -> Verified Pattern Generator -> Role-based Inbox."""
    clean_company = sanitize_company_name(company_data.name)
    known_founder = target_person or (company_data.founders[0] if company_data.founders else None)

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

    # 2. Tier 1 (Primary): Hunter.io domain-search & email-finder
    hunter_emails = await lookup_hunter_domain_search(domain) if domain else []
    best_hunter = _pick_best_hunter_contact(
        hunter_emails,
        target_person=known_founder,
        opportunity_type=opportunity_type,
    )
    if best_hunter and best_hunter.email:
        logger.info(
            f"Hunter.io primary match for {clean_company}: {best_hunter.name} <{best_hunter.email}>"
        )
        return best_hunter

    if domain and known_founder:
        finder_hit = await lookup_hunter_email_finder(domain, known_founder)
        if finder_hit and finder_hit.get("email"):
            score = int(finder_hit.get("score") or 0)
            ver_status = ((finder_hit.get("verification") or {}).get("status") or "").lower()
            if score >= 70 or ver_status == "valid":
                return ContactInfoResult(
                    name=known_founder,
                    title=finder_hit.get("position") or "Founding Team & Leadership",
                    email=finder_hit["email"].lower().strip(),
                    email_confidence="verified",
                    linkedin_url=finder_hit.get("linkedin_url"),
                )

    # 3. Tier 2: Scrape website for direct contact/team emails (concurrent)
    site_emails = await scrape_website_emails(domain) if domain else []

    # 4. Tier 3: Search web for Founder/CTO LinkedIn profiles and contact details
    snippets: List[str] = []
    if site_emails:
        snippets.append(f"Official Company Website Emails: {', '.join(site_emails)}")
    if hunter_emails:
        hunter_summary = "; ".join(
            f"{e.get('value')} ({e.get('first_name', '')} {e.get('last_name', '')}, {e.get('position') or 'unknown role'}, confidence {e.get('confidence')})"
            for e in hunter_emails
            if e.get("value")
        )
        if hunter_summary:
            snippets.append(f"Hunter.io Domain Search Results: {hunter_summary}")

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

    # 5. Use LLM to cleanly extract executive name, title, verified LinkedIn URL, and email
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
4. If a direct email is found in the Official Company Website Emails or Hunter.io results above for this person, use that exact email and set email_confidence to 'verified'. Otherwise leave email null - do not guess a pattern yourself, that is handled separately.
"""

    try:
        contact_res = await client.generate_structured(
            prompt=prompt,
            response_schema=ContactInfoResult,
            use_smart=False,
        )
    except Exception as e:
        logger.warning(f"LLM contact extraction fallback: {e}")
        fallback_name = known_founder or "Founding Team"
        contact_res = ContactInfoResult(
            name=fallback_name,
            title="Founding Team & Leadership",
            email=None,
            email_confidence="missing",
            linkedin_url=None,
        )

    if known_founder:
        contact_res.name = known_founder

    # 5b. Hunter.io Email Finder on the LLM-discovered person if still unverified
    if (
        domain
        and contact_res.name
        and contact_res.name != "Founding Team"
        and not (contact_res.email and contact_res.email_confidence == "verified")
    ):
        finder_hit = await lookup_hunter_email_finder(domain, contact_res.name)
        if finder_hit and finder_hit.get("email"):
            score = int(finder_hit.get("score") or 0)
            ver_status = ((finder_hit.get("verification") or {}).get("status") or "").lower()
            if score >= 70 or ver_status == "valid":
                contact_res.email = finder_hit["email"].lower().strip()
                contact_res.email_confidence = "verified"
                contact_res.pattern_used = None
                contact_res.linkedin_url = contact_res.linkedin_url or finder_hit.get("linkedin_url")
                contact_res.title = contact_res.title or finder_hit.get("position") or "Founding Team & Leadership"

    # 6. Apollo person match (tier 3 - only worth trying once we have a name to match against)
    if domain and not (contact_res.email and contact_res.email_confidence == "verified"):
        apollo_person = await lookup_apollo_person(domain, contact_res.name)
        if apollo_person and apollo_person.get("email"):
            contact_res.email = apollo_person["email"].lower().strip()
            contact_res.email_confidence = "verified"
            contact_res.pattern_used = None
            contact_res.linkedin_url = contact_res.linkedin_url or apollo_person.get("linkedin_url")
            contact_res.title = contact_res.title or apollo_person.get("title") or "Founding Team & Leadership"

    # 7. If still nothing verified, fall back to ranked + SMTP-probed pattern guessing
    if domain and not (contact_res.email and contact_res.email_confidence == "verified"):
        name_for_pattern = contact_res.name or known_founder or ""
        name_parts = name_for_pattern.split()
        first = name_parts[0] if name_parts else ""
        last = name_parts[-1] if len(name_parts) > 1 else None
        if first:
            guessed_email, pattern_type, confidence = await _best_guessed_email(
                first, last, domain, pattern_success_rates
            )
            if guessed_email:
                contact_res.email = guessed_email
                contact_res.email_confidence = confidence
                contact_res.pattern_used = pattern_type

    # 8. Absolute last resort: a verified (SMTP-confirmed) generic role inbox
    if domain and not contact_res.email:
        role_email = await _find_role_based_inbox(domain)
        if role_email:
            contact_res.email = role_email
            contact_res.email_confidence = "verified"
            contact_res.name = contact_res.name or "Founding Team"
            contact_res.title = contact_res.title or "Founding Team & Leadership"

    if not contact_res.name:
        contact_res.name = known_founder or "Founding Team"
    if not contact_res.title:
        contact_res.title = "Founding Team & Leadership"
    if not contact_res.email:
        contact_res.email_confidence = "missing"

    return contact_res
