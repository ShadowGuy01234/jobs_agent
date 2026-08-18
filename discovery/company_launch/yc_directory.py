"""Y Combinator Directory and Batch connector."""

import logging
from typing import List, Optional
import httpx

from discovery.base import BaseDiscoveryConnector
from discovery.models import CompanyInfo, DiscoverySource, OpportunityType, RawOpportunity

logger = logging.getLogger(__name__)


class YCDirectoryConnector(BaseDiscoveryConnector):
    source_name = DiscoverySource.YC_DIRECTORY

    def __init__(self, batches: Optional[List[str]] = None):
        # Target recent batches
        self.batches = batches or ["W25", "S24", "W24", "F24"]

    async def fetch_opportunities(self, limit: int = 30) -> List[RawOpportunity]:
        opportunities: List[RawOpportunity] = []
        # Query YC public open dataset / Algolia API
        algolia_url = "https://45bwzj1sgc-dsn.algolia.net/1/indexes/yc_companies/query"
        headers = {
            "x-algolia-api-key": "d61994e1d1678887955513ab026e6d19",
            "x-algolia-application-id": "45BWZJ1SGC",
        }

        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                for batch in self.batches:
                    payload = {
                        "query": "",
                        "filters": f'batch:"{batch}"',
                        "hitsPerPage": 25,
                    }
                    resp = await client.post(algolia_url, headers=headers, json=payload)
                    if resp.status_code != 200:
                        logger.debug(f"YC Algolia returned HTTP {resp.status_code} for batch {batch}")
                        continue

                    data = resp.json()
                    hits = data.get("hits", [])

                    for hit in hits:
                        name = hit.get("name", "")
                        if not name:
                            continue

                        website = hit.get("website", "")
                        domain = None
                        if website:
                            domain = website.replace("https://", "").replace("http://", "").split("/")[0].replace("www.", "")

                        description = hit.get("one_liner") or hit.get("long_description", "")
                        industry = hit.get("industry", "")
                        subindustry = hit.get("subindustry", "")
                        tech_stack = [s for s in [industry, subindustry] if s]
                        founders = hit.get("founders", [])
                        founder_names = [f.get("name", "") for f in founders if isinstance(f, dict) and f.get("name")]

                        company_info = CompanyInfo(
                            name=name,
                            domain=domain,
                            website=website,
                            stage="seed",
                            source=f"YC {batch}",
                            description=description,
                            tech_stack=tech_stack,
                            funding_info=f"Y Combinator {batch}",
                            country=hit.get("country", "Remote"),
                            is_stealth=False,
                            founders=founder_names,
                        )

                        yc_url = f"https://www.ycombinator.com/companies/{hit.get('slug', name.lower().replace(' ', '-'))}"

                        opp = RawOpportunity(
                            source=self.source_name,
                            type=OpportunityType.FOUNDER_REACHOUT,
                            title=f"{name} ({batch}) — {description[:80]}",
                            url=yc_url,
                            company=company_info,
                            external_id=str(hit.get("id")),
                            location=hit.get("location", "Remote"),
                            is_remote=True,
                            raw_content=hit.get("long_description") or description,
                            metadata={"batch": batch, "team_size": hit.get("team_size")},
                        )
                        opportunities.append(opp)
                        if len(opportunities) >= limit:
                            return opportunities

        except Exception as e:
            logger.warning(f"Error fetching YC directory: {e}")

        return opportunities[:limit]
