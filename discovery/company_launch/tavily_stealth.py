"""Tavily search queries connector for stealth startup founder signals."""

import logging
from typing import List, Optional
import httpx

from config import settings
from discovery.base import BaseDiscoveryConnector
from discovery.models import CompanyInfo, DiscoverySource, OpportunityType, RawOpportunity

logger = logging.getLogger(__name__)


class TavilyStealthConnector(BaseDiscoveryConnector):
    source_name = DiscoverySource.TAVILY_STEALTH

    def __init__(self, api_key: Optional[str] = None):
        self.api_key = api_key or settings.TAVILY_API_KEY
        self.search_queries = [
            'site:linkedin.com/in ("Founder at Stealth" OR "Co-Founder at Stealth") ("AI" OR "Infrastructure") ("ex-Google" OR "ex-OpenAI" OR "ex-Meta" OR "ex-Stripe")',
            '"raised seed" "stealth" ("AI" OR "Developer Tools" OR "Distributed Systems")',
        ]

    async def fetch_opportunities(self, limit: int = 10) -> List[RawOpportunity]:
        if not self.api_key:
            logger.info("TAVILY_API_KEY not configured. Skipping Tavily stealth search.")
            return []

        opportunities: List[RawOpportunity] = []
        tavily_url = "https://api.tavily.com/search"

        try:
            async with httpx.AsyncClient(timeout=20.0) as client:
                for query in self.search_queries:
                    payload = {
                        "api_key": self.api_key,
                        "query": query,
                        "search_depth": "basic",
                        "include_answer": False,
                        "max_results": 5,
                    }
                    resp = await client.post(tavily_url, json=payload)
                    if resp.status_code != 200:
                        logger.debug(f"Tavily search returned HTTP {resp.status_code}")
                        continue

                    data = resp.json()
                    results = data.get("results", [])

                    for item in results:
                        title = item.get("title", "")
                        url = item.get("url", "")
                        content = item.get("content", "")

                        # Parse company or founder from title
                        company_name = title.split("-")[0].split("|")[0].split("–")[0].strip()

                        company_info = CompanyInfo(
                            name=company_name,
                            domain=None,
                            website=url,
                            stage="pre_seed",
                            source="Tavily Stealth Search",
                            description=content[:200],
                            is_stealth=True,
                        )

                        opp = RawOpportunity(
                            source=self.source_name,
                            type=OpportunityType.STEALTH_REACHOUT,
                            title=f"{company_name} (Stealth Founder Signal)",
                            url=url,
                            company=company_info,
                            location="Remote",
                            is_remote=True,
                            raw_content=content,
                            metadata={"query": query},
                        )
                        opportunities.append(opp)
                        if len(opportunities) >= limit:
                            return opportunities

        except Exception as e:
            logger.warning(f"Error during Tavily stealth sweep: {e}")

        return opportunities[:limit]
