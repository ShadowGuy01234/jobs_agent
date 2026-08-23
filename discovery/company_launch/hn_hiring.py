"""Hacker News "Ask HN: Who is hiring?" connector.

The existing hackernews.py connector only queries "Launch HN" and "Show HN", so it misses the
monthly hiring thread entirely — which is the single richest free source of seed/Series-A
startup roles (typically 200-400 companies per month, one top-level comment each).

Uses the same free hn.algolia.com API the other HN connector already calls. No key required.
"""

import html
import logging
import re
from typing import List, Optional
import httpx

from discovery.base import BaseDiscoveryConnector
from discovery.models import CompanyInfo, DiscoverySource, OpportunityType, RawOpportunity

logger = logging.getLogger(__name__)

# The monthly threads are all posted by the "whoishiring" bot account.
HN_THREAD_SEARCH = (
    "https://hn.algolia.com/api/v1/search_by_date"
    "?tags=story,author_whoishiring&hitsPerPage=10"
)
HN_ITEM_URL = "https://hn.algolia.com/api/v1/items/{story_id}"

_TAG_RE = re.compile(r"<[^>]+>")
_URL_RE = re.compile(r"https?://[^\s|<>()\"]+")
_ROLE_RE = re.compile(
    r"engineer|developer|scientist|designer|manager|staff|lead|architect|founding|swe|sre|devops",
    re.I,
)


def _plain_text(raw_html: str) -> str:
    """HN comment text is HTML; flatten it to a single clean line of prose."""
    text = _TAG_RE.sub(" ", raw_html or "")
    return re.sub(r"\s+", " ", html.unescape(text)).strip()


def _parse_entry(text: str) -> tuple[str, str, Optional[str], bool]:
    """Pull (company, role_title, website, is_remote) out of one hiring comment.

    The thread convention is pipe-delimited: "Company | Role | Location | REMOTE | ...".
    Parsing is best-effort — the pipeline's LLM enrichment node reads raw_content anyway, so
    this only needs to be good enough for dedup keys and the title relevance filter.
    """
    url_match = _URL_RE.search(text)
    website = url_match.group(0).rstrip(".,);") if url_match else None

    segments = [s.strip() for s in text.split("|") if s.strip()]
    if not segments:
        return text[:60], text[:120], website, "remote" in text.lower()

    # Company is the first segment, minus any inline URL or parenthetical.
    company = _URL_RE.sub("", segments[0])
    company = re.sub(r"\([^)]*\)", "", company).strip(" -–—,")
    company = company.split(" - ")[0].strip() or segments[0][:60]

    # Role is whichever later segment carries a job-ish word.
    role = ""
    for seg in segments[1:]:
        if _ROLE_RE.search(seg):
            role = seg
            break

    # Posters don't all follow the pipe convention. Rather than letting a stray description
    # fragment become the title (which the title-relevance filter would then reject as
    # non-engineering), fall back to a generic role when the body clearly is an eng posting.
    if not role:
        role = "Engineering role" if _ROLE_RE.search(text) else (segments[1] if len(segments) > 1 else "")

    is_remote = "remote" in text.lower()
    return company[:80], (role or "Engineering role")[:140], website, is_remote


class HNHiringConnector(BaseDiscoveryConnector):
    source_name = DiscoverySource.HN_HIRING

    def __init__(self, max_threads: int = 1):
        # How many recent monthly threads to read; 1 = the current month only.
        self.max_threads = max_threads

    async def _latest_thread_ids(self, client: httpx.AsyncClient) -> List[int]:
        resp = await client.get(HN_THREAD_SEARCH)
        resp.raise_for_status()
        hits = resp.json().get("hits", [])
        # "Who wants to be hired?" shares the author; keep only the hiring threads.
        ids = [
            int(h["objectID"])
            for h in hits
            if "who is hiring" in (h.get("title") or "").lower()
        ]
        return ids[: self.max_threads]

    async def fetch_opportunities(self, limit: int = 25) -> List[RawOpportunity]:
        opportunities: List[RawOpportunity] = []
        seen_companies: set[str] = set()

        try:
            async with httpx.AsyncClient(timeout=30.0, follow_redirects=True) as client:
                for story_id in await self._latest_thread_ids(client):
                    resp = await client.get(HN_ITEM_URL.format(story_id=story_id))
                    if resp.status_code != 200:
                        logger.warning(f"HN item {story_id} returned HTTP {resp.status_code}")
                        continue

                    for child in resp.json().get("children", []):
                        raw = child.get("text")
                        if not raw:
                            continue  # deleted/flagged comment

                        text = _plain_text(raw)
                        if len(text) < 40:
                            continue

                        company, role, website, is_remote = _parse_entry(text)
                        key = company.lower()
                        if not company or key in seen_companies:
                            continue
                        seen_companies.add(key)

                        domain = None
                        if website:
                            domain = (
                                website.replace("https://", "")
                                .replace("http://", "")
                                .split("/")[0]
                                .replace("www.", "")
                            )

                        opportunities.append(
                            RawOpportunity(
                                source=self.source_name,
                                type=OpportunityType.JOB_POSTING,
                                title=f"{role} at {company}",
                                # Permalink to the specific comment: stable and unique, which
                                # matters because dedup keys off opportunities.url.
                                url=f"https://news.ycombinator.com/item?id={child['id']}",
                                company=CompanyInfo(
                                    name=company,
                                    domain=domain,
                                    website=website,
                                    # Unknown stage is intentional: the stage knockout skips
                                    # "unknown", so LLM enrichment gets to decide.
                                    stage="unknown",
                                    source=self.source_name.value,
                                    description=text[:400],
                                ),
                                external_id=str(child["id"]),
                                location="Remote" if is_remote else "See posting",
                                is_remote=is_remote,
                                raw_content=text[:4000],
                            )
                        )
                        if len(opportunities) >= limit:
                            return opportunities

        except Exception as e:
            logger.warning(f"Error fetching HN hiring thread: {e}")

        return opportunities[:limit]
