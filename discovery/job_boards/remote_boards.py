"""Free remote-job aggregator connector (Remotive, RemoteOK, Arbeitnow, Himalayas).

Four public keyless JSON endpoints in one connector. High volume, lower signal than the
curated startup boards — these feeds carry retail, medical and support roles alongside
engineering — so titles are filtered here at ingest rather than downstream. Letting thousands
of irrelevant rows into SQLite would starve the hourly sweep's backlog slots and waste LLM
scoring calls on jobs that can never match.

Attribution note: RemoteOK's API terms ask consumers to credit Remote OK and link back. Every
opportunity keeps its canonical remoteok.com URL, which is what the outreach flow surfaces.
"""

import html as html_lib
import logging
import re
from typing import Any, Callable, Dict, List, Optional, Tuple
import httpx

from discovery.base import BaseDiscoveryConnector
from discovery.models import CompanyInfo, DiscoverySource, OpportunityType, RawOpportunity
from pipeline.nodes.score_fit import check_title_relevance

logger = logging.getLogger(__name__)

FEEDS: Dict[str, str] = {
    "remotive": "https://remotive.com/api/remote-jobs?limit=200",
    "remoteok": "https://remoteok.com/api",
    "arbeitnow": "https://www.arbeitnow.com/api/job-board-api",
    "himalayas": "https://himalayas.app/jobs/api?limit=200",
}

# Several of these feeds reject requests without a browser-ish User-Agent.
_HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; job-outreach/1.0)"}

_TAG_RE = re.compile(r"<[^>]+>")


def _clean(text: Optional[str], limit: int = 3000) -> str:
    """Feed descriptions are HTML (sometimes double-escaped); flatten to plain text."""
    if not text:
        return ""
    flat = _TAG_RE.sub(" ", text)
    for entity, char in (("&lt;", "<"), ("&gt;", ">"), ("&quot;", '"'), ("&amp;", "&"), ("&nbsp;", " ")):
        flat = flat.replace(entity, char)
    flat = _TAG_RE.sub(" ", flat)
    return re.sub(r"\s+", " ", flat).strip()[:limit]


def _domain_of(url: Optional[str]) -> Optional[str]:
    if not url:
        return None
    return url.replace("https://", "").replace("http://", "").split("/")[0].replace("www.", "") or None


# Each parser maps one feed's payload to (title, company, url, location, is_remote, description).
Row = Tuple[str, str, str, str, bool, str]


def _parse_remotive(payload: Any) -> List[Row]:
    return [
        (
            j.get("title", ""),
            j.get("company_name", ""),
            j.get("url", ""),
            j.get("candidate_required_location") or "Remote",
            True,
            _clean(j.get("description")),
        )
        for j in payload.get("jobs", [])
    ]


def _parse_remoteok(payload: Any) -> List[Row]:
    rows: List[Row] = []
    for j in payload:
        # The first element is RemoteOK's legal/attribution notice, not a job.
        if not isinstance(j, dict) or "position" not in j:
            continue
        rows.append(
            (
                j.get("position", ""),
                j.get("company", ""),
                j.get("url") or j.get("apply_url", ""),
                j.get("location") or "Remote",
                True,
                _clean(j.get("description")),
            )
        )
    return rows


def _parse_arbeitnow(payload: Any) -> List[Row]:
    return [
        (
            j.get("title", ""),
            j.get("company_name", ""),
            j.get("url", ""),
            j.get("location") or "Remote",
            bool(j.get("remote")),
            _clean(j.get("description")),
        )
        for j in payload.get("data", [])
    ]


def _parse_himalayas(payload: Any) -> List[Row]:
    rows: List[Row] = []
    for j in payload.get("jobs", []):
        locations = j.get("locationRestrictions") or []
        rows.append(
            (
                j.get("title", ""),
                j.get("companyName", ""),
                j.get("applicationLink", ""),
                ", ".join(locations) if locations else "Remote Worldwide",
                True,
                _clean(j.get("description") or j.get("excerpt")),
            )
        )
    return rows


PARSERS: Dict[str, Callable[[Any], List[Row]]] = {
    "remotive": _parse_remotive,
    "remoteok": _parse_remoteok,
    "arbeitnow": _parse_arbeitnow,
    "himalayas": _parse_himalayas,
}


class RemoteBoardsConnector(BaseDiscoveryConnector):
    source_name = DiscoverySource.REMOTE_BOARDS

    def __init__(self, feeds: Optional[List[str]] = None):
        self.feeds = feeds or list(FEEDS)

    async def _fetch_feed(self, client: httpx.AsyncClient, name: str) -> List[Row]:
        try:
            resp = await client.get(FEEDS[name])
            if resp.status_code != 200:
                logger.warning(f"Remote feed {name} returned HTTP {resp.status_code}")
                return []
            return PARSERS[name](resp.json())
        except Exception as e:
            logger.warning(f"Error fetching remote feed {name}: {e}")
            return []

    async def fetch_opportunities(self, limit: int = 25) -> List[RawOpportunity]:
        opportunities: List[RawOpportunity] = []
        seen: set[str] = set()
        per_feed = max(1, limit // max(1, len(self.feeds)))

        async with httpx.AsyncClient(timeout=25.0, follow_redirects=True, headers=_HEADERS) as client:
            for name in self.feeds:
                if name not in FEEDS:
                    logger.warning(f"Unknown remote feed '{name}', skipping.")
                    continue

                kept = 0
                for title, company, url, location, is_remote, description in await self._fetch_feed(client, name):
                    if kept >= per_feed:
                        break
                    if not title or not company or not url or not is_remote:
                        continue
                    # Feeds ship entity-escaped names ("Larsen &amp; Toubro").
                    title = html_lib.unescape(title).strip()
                    company = html_lib.unescape(company).strip()
                    # Drop non-engineering roles before they reach SQLite.
                    if check_title_relevance(title, "job_posting"):
                        continue
                    if url in seen:
                        continue
                    seen.add(url)

                    opportunities.append(
                        RawOpportunity(
                            source=self.source_name,
                            type=OpportunityType.JOB_POSTING,
                            title=title,
                            url=url,
                            company=CompanyInfo(
                                name=company,
                                domain=_domain_of(url) if name == "arbeitnow" else None,
                                # Aggregators don't publish funding stage; "unknown" is skipped
                                # by the stage knockout so LLM enrichment gets to decide.
                                stage="unknown",
                                source=f"{self.source_name.value}:{name}",
                                description=description[:400],
                            ),
                            location=location,
                            is_remote=True,
                            raw_content=description,
                            metadata={"feed": name},
                        )
                    )
                    kept += 1

                if kept:
                    logger.info(f"Remote feed {name}: kept {kept} engineering role(s).")

        return opportunities[:limit]
