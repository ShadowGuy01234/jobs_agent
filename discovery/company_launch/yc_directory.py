"""Y Combinator Directory connector, backed by the free yc-oss public API mirror.

This previously queried YC's own Algolia index using the app-id/key scraped from the directory
frontend. Those credentials now return HTTP 403, and because a non-200 was only logged at debug
level the connector silently returned zero opportunities on every sweep.

yc-oss.github.io/api is a free, key-less, daily-refreshed mirror of the public YC directory. It
also exposes the authoritative batch list, so recency comes from YC's own naming rather than
being guessed from the calendar.
"""

import logging
from typing import Dict, List, Optional, Tuple
import httpx

from discovery.base import BaseDiscoveryConnector
from discovery.models import CompanyInfo, DiscoverySource, OpportunityType, RawOpportunity

logger = logging.getLogger(__name__)

YC_API_META = "https://yc-oss.github.io/api/meta.json"

# Batch slugs look like "winter-2027" / "summer-2025"; this orders them within a year.
_SEASON_ORDER = {"winter": 0, "spring": 1, "summer": 2, "fall": 3}

# YC's own stage vocabulary -> the stage names used by the targeting knockouts.
_STAGE_MAP = {"early": "seed", "growth": "series_b"}


def _batch_sort_key(slug: str) -> Tuple[int, int]:
    """Sort key for a batch slug; unparseable slugs sort last."""
    try:
        season, year = slug.rsplit("-", 1)
        return (int(year), _SEASON_ORDER.get(season.lower(), -1))
    except Exception:
        return (-1, -1)


async def fetch_recent_batches(
    client: httpx.AsyncClient, count: int = 4
) -> List[Tuple[str, str]]:
    """Return [(batch_slug, api_url)] for the `count` most recent non-empty YC batches."""
    resp = await client.get(YC_API_META)
    resp.raise_for_status()
    batches: Dict[str, dict] = resp.json().get("batches", {})

    usable = [
        (slug, meta["api"])
        for slug, meta in batches.items()
        if meta.get("api") and meta.get("count", 0) > 0 and _batch_sort_key(slug) != (-1, -1)
    ]
    usable.sort(key=lambda pair: _batch_sort_key(pair[0]), reverse=True)
    return usable[:count]


class YCDirectoryConnector(BaseDiscoveryConnector):
    source_name = DiscoverySource.YC_DIRECTORY

    def __init__(self, batches: Optional[List[str]] = None):
        # Explicit batch slugs (e.g. ["summer-2025"]); None = auto-pick the most recent.
        self.batches = batches

    async def fetch_opportunities(self, limit: int = 30) -> List[RawOpportunity]:
        opportunities: List[RawOpportunity] = []

        try:
            async with httpx.AsyncClient(timeout=20.0, follow_redirects=True) as client:
                if self.batches:
                    targets = [
                        (b, f"https://yc-oss.github.io/api/batches/{b}.json") for b in self.batches
                    ]
                else:
                    targets = await fetch_recent_batches(client)

                for batch_slug, api_url in targets:
                    try:
                        resp = await client.get(api_url)
                        if resp.status_code != 200:
                            logger.warning(
                                f"YC batch {batch_slug} returned HTTP {resp.status_code} from {api_url}"
                            )
                            continue
                        companies = resp.json()
                    except Exception as e:
                        logger.warning(f"Error fetching YC batch {batch_slug}: {e}")
                        continue

                    for hit in companies:
                        name = (hit.get("name") or "").strip()
                        if not name or hit.get("status") == "Inactive":
                            continue

                        website = hit.get("website") or ""
                        domain = None
                        if website:
                            domain = (
                                website.replace("https://", "")
                                .replace("http://", "")
                                .split("/")[0]
                                .replace("www.", "")
                            )

                        description = (hit.get("one_liner") or hit.get("long_description") or "").strip()
                        tech_stack = [t for t in (hit.get("tags") or []) if t][:6]
                        batch_label = hit.get("batch") or batch_slug

                        company_info = CompanyInfo(
                            name=name,
                            domain=domain,
                            website=website,
                            stage=_STAGE_MAP.get(str(hit.get("stage", "")).lower(), "seed"),
                            source=f"YC {batch_label}",
                            description=description,
                            tech_stack=tech_stack,
                            funding_info=f"Y Combinator {batch_label}",
                            country=(hit.get("regions") or ["Remote"])[0],
                            is_stealth=False,
                        )

                        slug = hit.get("slug") or name.lower().replace(" ", "-")
                        opp = RawOpportunity(
                            source=self.source_name,
                            type=OpportunityType.FOUNDER_REACHOUT,
                            title=f"{name} ({batch_label}) — {description[:80]}",
                            url=f"https://www.ycombinator.com/companies/{slug}",
                            company=company_info,
                            external_id=str(hit.get("id")),
                            location=hit.get("all_locations") or "Remote",
                            is_remote=True,
                            raw_content=hit.get("long_description") or description,
                            metadata={
                                "batch": batch_label,
                                "team_size": hit.get("team_size"),
                                # Publicly advertising open roles - a useful ranking signal.
                                "is_hiring": bool(hit.get("isHiring")),
                            },
                        )
                        opportunities.append(opp)
                        if len(opportunities) >= limit:
                            return opportunities

        except Exception as e:
            logger.warning(f"Error fetching YC directory: {e}")

        return opportunities[:limit]
