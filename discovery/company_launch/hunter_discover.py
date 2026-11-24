"""Hunter.io Discover API connector — primary company & startup discovery source."""

import asyncio
import html as html_lib
import logging
import re
from typing import Any, Dict, List, Optional

import httpx

from config import settings
from discovery.base import BaseDiscoveryConnector
from discovery.models import CompanyInfo, DiscoverySource, OpportunityType, RawOpportunity

logger = logging.getLogger(__name__)

HUNTER_DISCOVER_URL = "https://api.hunter.io/v2/discover"

DEFAULT_INDUSTRIES = [
    "Software Development",
    "Technology, Information and Internet",
]

DEFAULT_KEYWORD_BATCHES: List[List[str]] = [
    ["AI", "agent", "LLM"],
    ["developer", "devtools", "infrastructure"],
    ["API", "cloud", "backend"],
    ["vision", "robotics", "edge"],
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


def _extract_site_summary(html_text: str) -> tuple[str, Optional[str]]:
    """Extract clean page title/meta description and optional careers link from homepage HTML."""
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
    return " — ".join(parts)[:600], careers_href


class HunterDiscoverConnector(BaseDiscoveryConnector):
    """Primary startup & company discovery connector powered by Hunter.io /v2/discover."""

    source_name = DiscoverySource.HUNTER_DISCOVER

    def __init__(
        self,
        api_key: Optional[str] = None,
        keyword_batches: Optional[List[List[str]]] = None,
        headcounts: Optional[List[str]] = None,
        industries: Optional[List[str]] = None,
    ):
        self.api_key = api_key if api_key is not None else settings.HUNTER_API_KEY
        self.keyword_batches = keyword_batches or DEFAULT_KEYWORD_BATCHES
        self.headcounts = headcounts or ["1-10", "11-50"]
        self.industries = industries or DEFAULT_INDUSTRIES
        self._batch_index = 0

    async def _enrich_homepage(
        self, client: httpx.AsyncClient, sem: asyncio.Semaphore, domain: str
    ) -> tuple[str, Optional[str]]:
        """Best-effort fetch of homepage title/description and careers hint."""
        async with sem:
            try:
                resp = await client.get(f"https://{domain}", timeout=5.0)
                if resp.status_code == 200 and resp.text:
                    return _extract_site_summary(resp.text)
            except Exception:
                pass
        return "", None

    async def fetch_opportunities(self, limit: int = 20) -> List[RawOpportunity]:
        if not self.api_key:
            logger.info("HUNTER_API_KEY not configured. Skipping Hunter Discover.")
            return []

        keywords = self.keyword_batches[self._batch_index % len(self.keyword_batches)]
        self._batch_index += 1

        payload: Dict[str, Any] = {
            "industry": {"include": self.industries},
            "headcount": self.headcounts,
            "keywords": {"include": keywords},
            "limit": min(max(limit * 2, 10), 100),
        }

        try:
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
                # Prefer companies that actually have personal emails indexed in Hunter
                candidates = [
                    r
                    for r in rows
                    if r.get("domain")
                    and (r.get("emails_count") or {}).get("personal", 0) > 0
                ]
                if not candidates:
                    candidates = [r for r in rows if r.get("domain")]
                candidates = candidates[:limit]

                sem = asyncio.Semaphore(5)
                summaries = await asyncio.gather(
                    *(self._enrich_homepage(client, sem, r["domain"]) for r in candidates)
                )

                opportunities: List[RawOpportunity] = []
                for item, (site_summary, careers_href) in zip(candidates, summaries):
                    domain = item["domain"].lower().strip()
                    org_name = (item.get("organization") or domain).strip()
                    emails_count = item.get("emails_count") or {}
                    personal_cnt = emails_count.get("personal", 0)
                    total_cnt = emails_count.get("total", 0)
                    website = f"https://{domain}"
                    desc = site_summary or (
                        f"{org_name} ({domain}) — discovered via Hunter.io ({', '.join(keywords)})."
                    )
                    careers_note = f" Careers page detected: {careers_href}." if careers_href else ""

                    company_info = CompanyInfo(
                        name=org_name,
                        domain=domain,
                        website=website,
                        stage="seed",
                        description=desc[:400],
                        tech_stack=list(keywords),
                        funding_info=f"Hunter Discover ({personal_cnt} personal / {total_cnt} emails)",
                        country="Remote",
                        is_stealth=False,
                    )

                    opp = RawOpportunity(
                        source=self.source_name,
                        type=OpportunityType.FOUNDER_REACHOUT,
                        title=f"{org_name} — {', '.join(keywords)} Startup ({domain})",
                        url=website,
                        company=company_info,
                        external_id=domain,
                        location="Remote",
                        is_remote=True,
                        raw_content=f"{desc}{careers_note}".strip(),
                        metadata={
                            "keywords": keywords,
                            "emails_count": emails_count,
                            "careers_href": careers_href,
                        },
                    )
                    opportunities.append(opp)

                return opportunities[:limit]
        except Exception as e:
            logger.warning(f"Error during Hunter Discover sweep: {e}")
            return []
