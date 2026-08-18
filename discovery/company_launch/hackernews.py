"""Hacker News Launch HN & Show HN connector."""

import logging
from typing import List, Optional
import httpx

from discovery.base import BaseDiscoveryConnector
from discovery.models import CompanyInfo, DiscoverySource, OpportunityType, RawOpportunity

logger = logging.getLogger(__name__)


class HackerNewsConnector(BaseDiscoveryConnector):
    source_name = DiscoverySource.HACKER_NEWS

    def __init__(self, queries: Optional[List[str]] = None):
        self.queries = queries or ["Launch HN", "Show HN"]

    async def fetch_opportunities(self, limit: int = 25) -> List[RawOpportunity]:
        opportunities: List[RawOpportunity] = []
        base_url = "https://hn.algolia.com/api/v1/search_by_date"

        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                for q in self.queries:
                    params = {
                        "query": q,
                        "tags": "story",
                        "hitsPerPage": 20,
                    }
                    resp = await client.get(base_url, params=params)
                    if resp.status_code != 200:
                        continue

                    data = resp.json()
                    hits = data.get("hits", [])

                    for hit in hits:
                        title = hit.get("title", "")
                        if not (title.startswith("Launch HN:") or title.startswith("Show HN:")):
                            continue

                        hn_id = str(hit.get("objectID", ""))
                        hn_url = f"https://news.ycombinator.com/item?id={hn_id}"
                        external_url = hit.get("url") or hn_url
                        author = hit.get("author", "Founder")
                        story_text = hit.get("story_text") or ""

                        # Parse company name from "Launch HN: CompanyName (YC W25) - One Liner"
                        raw_name = title.replace("Launch HN:", "").replace("Show HN:", "").strip()
                        company_name = raw_name.split("(")[0].split("–")[0].split("-")[0].split(":")[0].strip()

                        domain = None
                        if external_url and "news.ycombinator.com" not in external_url:
                            domain = external_url.replace("https://", "").replace("http://", "").split("/")[0].replace("www.", "")

                        company_info = CompanyInfo(
                            name=company_name,
                            domain=domain,
                            website=external_url,
                            stage="seed" if "Launch HN" in title else "pre_seed",
                            source="Hacker News",
                            description=title,
                            founders=[author],
                        )

                        opp = RawOpportunity(
                            source=self.source_name,
                            type=OpportunityType.FOUNDER_REACHOUT,
                            title=title,
                            url=hn_url,
                            company=company_info,
                            external_id=hn_id,
                            location="Remote",
                            is_remote=True,
                            raw_content=story_text or title,
                            metadata={"author": author, "points": hit.get("points")},
                        )
                        opportunities.append(opp)
                        if len(opportunities) >= limit:
                            return opportunities

        except Exception as e:
            logger.warning(f"Error fetching Hacker News launches: {e}")

        return opportunities[:limit]
