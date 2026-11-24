"""Hunter.io Discover API connector — primary company & startup discovery source."""

import asyncio
import html as html_lib
import logging
import re
from typing import Any, Dict, List, Optional

import httpx

from config import settings
from db.database import get_app_setting, get_known_company_domains, set_app_setting
from discovery.base import BaseDiscoveryConnector
from discovery.board_tokens import register_discovered_board_tokens
from discovery.models import CompanyInfo, DiscoverySource, OpportunityType, RawOpportunity

logger = logging.getLogger(__name__)

HUNTER_DISCOVER_URL = "https://api.hunter.io/v2/discover"

DEFAULT_INDUSTRIES = [
    "Software Development",
    "Technology, Information and Internet",
]

DEFAULT_PRESETS: List[Dict[str, Any]] = [
    {"keywords": ["AI", "agent", "LLM"], "headcount": ["1-10", "11-50"], "label": "AI & Agents"},
    {"keywords": ["developer", "devtools", "infrastructure"], "headcount": ["1-10", "11-50"], "label": "DevTools & Infra"},
    {"keywords": ["API", "cloud", "backend"], "headcount": ["1-10", "11-50"], "label": "Cloud & APIs"},
    {"keywords": ["vision", "robotics", "edge"], "headcount": ["1-10", "11-50"], "label": "Vision & Edge AI"},
    {"keywords": ["AI", "SaaS", "software"], "headcount": ["1-10", "11-50", "51-200"], "countries": ["India"], "label": "India Tech Startups"},
    {"keywords": ["AI", "platform", "automation"], "headcount": ["11-50", "51-200"], "countries": ["United States"], "label": "US Seed/Series A"},
    {"keywords": ["security", "observability", "data"], "headcount": ["1-10", "11-50"], "label": "Data & Security"},
    {"keywords": ["machine learning", "vector", "rag"], "headcount": ["1-10", "11-50", "51-200"], "label": "ML Infra"},
]

_TITLE_RE = re.compile(r"<title[^>]*>(.*?)</title>", re.IGNORECASE | re.DOTALL)
_META_DESC_RE = re.compile(
    r'<meta[^>]+name=["\']description["\'][^>]+content=["\'](.*?)["\']',
    re.IGNORECASE | re.DOTALL,
)
_META_DESC_ALT_RE = re.compile(
    r'<meta[^>]+content=["\'](.*?)["\'][^>]+name=["\']description["\']',
    re.IGNORECASE | re.DOTALL,
)
_CAREERS_LINK_RE = re.compile(r'href=["\']([^"\']*(?:careers|jobs)[^"\']*)["\']', re.IGNORECASE)
_ATS_PATTERNS = {
    "ashby": re.compile(r"https?://jobs\.ashbyhq\.com/([a-z0-9][a-z0-9_-]{1,60})", re.IGNORECASE),
    "greenhouse": re.compile(r"https?://(?:boards|job-boards)\.greenhouse\.io/([a-z0-9][a-z0-9_-]{1,60})", re.IGNORECASE),
    "lever": re.compile(r"https?://jobs\.lever\.co/([a-z0-9][a-z0-9_-]{1,60})", re.IGNORECASE),
}


def _extract_site_summary(html_text: str) -> tuple[str, Optional[str], Dict[str, List[str]]]:
    """Extract page title/meta description, careers link, and any embedded ATS board slugs."""
    title_match = _TITLE_RE.search(html_text)
    desc_match = _META_DESC_RE.search(html_text) or _META_DESC_ALT_RE.search(html_text)
    careers_match = _CAREERS_LINK_RE.search(html_text)

    parts = []
    if title_match:
        title_txt = re.sub(r"\s+", " ", html_lib.unescape(title_match.group(1))).strip()
        if title_txt:
            parts.append(title_txt)
    if desc_match:
        desc_txt = re.sub(r"\s+", " ", html_lib.unescape(desc_match.group(1))).strip()
        if desc_txt and desc_txt not in parts:
            parts.append(desc_txt)

    careers_href = careers_match.group(1).strip() if careers_match else None
    ats_hits: Dict[str, List[str]] = {}
    for provider, pat in _ATS_PATTERNS.items():
        slugs = list(dict.fromkeys(m.lower() for m in pat.findall(html_text)))
        if slugs:
            ats_hits[provider] = slugs

    return " — ".join(parts)[:600], careers_href, ats_hits


class HunterDiscoverConnector(BaseDiscoveryConnector):
    """Primary startup & company discovery connector powered by Hunter.io /v2/discover."""

    source_name = DiscoverySource.HUNTER_DISCOVER

    def __init__(
        self,
        api_key: Optional[str] = None,
        presets: Optional[List[Dict[str, Any]]] = None,
        industries: Optional[List[str]] = None,
        use_persisted_cursor: bool = True,
    ):
        self.api_key = api_key if api_key is not None else settings.HUNTER_API_KEY
        self.presets = presets or DEFAULT_PRESETS
        self.industries = industries or DEFAULT_INDUSTRIES
        self.use_persisted_cursor = use_persisted_cursor and api_key is None
        self._batch_index = 0

    def _next_preset(self) -> Dict[str, Any]:
        idx = self._batch_index
        if self.use_persisted_cursor:
            try:
                saved = get_app_setting("hunter_discover_cursor")
                if saved is not None:
                    idx = int(saved)
                set_app_setting("hunter_discover_cursor", str((idx + 1) % len(self.presets)))
            except Exception as e:
                logger.debug(f"Could not read/write hunter_discover_cursor: {e}")
        self._batch_index = idx + 1
        return self.presets[idx % len(self.presets)]

    async def _enrich_homepage(
        self, client: httpx.AsyncClient, sem: asyncio.Semaphore, domain: str
    ) -> tuple[str, Optional[str], Dict[str, List[str]]]:
        """Best-effort fetch of homepage title/description, careers hint, and ATS board links."""
        async with sem:
            try:
                resp = await client.get(f"https://{domain}", timeout=5.0)
                if resp.status_code == 200 and resp.text:
                    return _extract_site_summary(resp.text)
            except Exception:
                pass
        return "", None, {}

    async def fetch_opportunities(self, limit: int = 20) -> List[RawOpportunity]:
        if not self.api_key:
            logger.info("HUNTER_API_KEY not configured. Skipping Hunter Discover.")
            return []

        preset = self._next_preset()
        keywords: List[str] = preset["keywords"]
        headcounts: List[str] = preset.get("headcount", ["1-10", "11-50"])
        countries: Optional[List[str]] = preset.get("countries")

        payload: Dict[str, Any] = {
            "industry": {"include": self.industries},
            "headcount": headcounts,
            "keywords": {"include": keywords},
            "limit": min(max(limit * 3, 25), 100),
        }
        if countries:
            payload["headquarters_location"] = {"include": countries}

        try:
            known_domains: set[str] = set()
            if self.use_persisted_cursor:
                try:
                    known_domains = get_known_company_domains()
                except Exception:
                    known_domains = set()

            async with httpx.AsyncClient(
                timeout=15.0,
                follow_redirects=True,
                headers={"User-Agent": "Mozilla/5.0 (compatible; job-outreach/1.0)"},
            ) as client:
                resp = await client.post(
                    HUNTER_DISCOVER_URL,
                    headers={"X-API-KEY": self.api_key},
                    json=payload,
                )
                if resp.status_code != 200:
                    logger.warning(
                        f"Hunter Discover returned HTTP {resp.status_code}: {resp.text[:200]}"
                    )
                    return []

                rows = resp.json().get("data", [])
                # Prefer unseen companies that have personal emails indexed in Hunter
                candidates = [
                    r
                    for r in rows
                    if r.get("domain")
                    and r["domain"].lower().strip() not in known_domains
                    and (r.get("emails_count") or {}).get("personal", 0) > 0
                ]
                if not candidates:
                    candidates = [
                        r
                        for r in rows
                        if r.get("domain") and r["domain"].lower().strip() not in known_domains
                    ]
                candidates = candidates[:limit]
                if not candidates:
                    return []

                sem = asyncio.Semaphore(5)
                summaries = await asyncio.gather(
                    *(self._enrich_homepage(client, sem, r["domain"]) for r in candidates)
                )

                discovered_ats: Dict[str, List[str]] = {}
                stage = "series_a" if headcounts == ["51-200"] else "seed"
                country_label = ", ".join(countries) if countries else "Remote"

                opportunities: List[RawOpportunity] = []
                for item, (site_summary, careers_href, ats_hits) in zip(candidates, summaries):
                    for prov, slugs in ats_hits.items():
                        discovered_ats.setdefault(prov, []).extend(slugs)

                    domain = item["domain"].lower().strip()
                    org_name = (item.get("organization") or domain).strip()
                    emails_count = item.get("emails_count") or {}
                    personal_cnt = emails_count.get("personal", 0)
                    total_cnt = emails_count.get("total", 0)
                    website = f"https://{domain}"
                    desc = site_summary or (
                        f"{org_name} ({domain}) — discovered via Hunter.io ({preset.get('label', ', '.join(keywords))})."
                    )
                    careers_note = f" Careers page detected: {careers_href}." if careers_href else ""

                    company_info = CompanyInfo(
                        name=org_name,
                        domain=domain,
                        website=website,
                        stage=stage,
                        description=desc[:400],
                        tech_stack=list(keywords),
                        funding_info=f"Hunter Discover ({personal_cnt} personal / {total_cnt} emails)",
                        country=country_label,
                        is_stealth=False,
                    )

                    opp = RawOpportunity(
                        source=self.source_name,
                        type=OpportunityType.FOUNDER_REACHOUT,
                        title=f"{org_name} — {', '.join(keywords)} Startup ({domain})",
                        url=website,
                        company=company_info,
                        external_id=domain,
                        location=country_label,
                        is_remote=True,
                        raw_content=f"{desc}{careers_note}".strip(),
                        metadata={
                            "preset": preset.get("label"),
                            "keywords": keywords,
                            "emails_count": emails_count,
                            "careers_href": careers_href,
                            "ats_boards": ats_hits,
                        },
                    )
                    opportunities.append(opp)

                if discovered_ats and self.use_persisted_cursor:
                    try:
                        added = register_discovered_board_tokens(discovered_ats)
                        if added:
                            logger.info(f"Hunter Discover harvested {added} new ATS board token(s): {discovered_ats}")
                    except Exception as e:
                        logger.debug(f"Could not save harvested ATS tokens: {e}")

                return opportunities[:limit]
        except Exception as e:
            logger.warning(f"Error during Hunter Discover sweep: {e}")
            return []
