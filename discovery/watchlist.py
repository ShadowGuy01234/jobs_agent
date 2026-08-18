"""Watchlist connector for hand-picked companies and target URLs."""

import logging
from typing import List, Optional
from discovery.base import BaseDiscoveryConnector
from discovery.models import CompanyInfo, DiscoverySource, OpportunityType, RawOpportunity

logger = logging.getLogger(__name__)


class WatchlistConnector(BaseDiscoveryConnector):
    source_name = DiscoverySource.WATCHLIST

    def __init__(self, target_startups: Optional[List[dict]] = None):
        # Default handpicked high-growth startups
        self.target_startups = target_startups or [
            {
                "name": "Cursor",
                "domain": "cursor.com",
                "website": "https://cursor.com",
                "stage": "series_a",
                "description": "AI-first code editor built for pair programming with LLMs.",
                "tech_stack": ["Python", "TypeScript", "C++", "LLM Inference"],
                "country": "United States",
            },
            {
                "name": "Linear",
                "domain": "linear.app",
                "website": "https://linear.app",
                "stage": "series_b",
                "description": "The issue tracking tool you'll actually enjoy using. Built for high-performance software teams.",
                "tech_stack": ["TypeScript", "GraphQL", "React", "Node.js"],
                "country": "Remote",
            },
            {
                "name": "Tavily",
                "domain": "tavily.com",
                "website": "https://tavily.com",
                "stage": "seed",
                "description": "Search engine built specifically for AI agents and LLMs.",
                "tech_stack": ["Python", "FastAPI", "Distributed Crawling"],
                "country": "Remote",
            },
            {
                "name": "Postman",
                "domain": "postman.com",
                "website": "https://postman.com",
                "stage": "series_d",
                "description": "API platform for building and using APIs.",
                "tech_stack": ["Node.js", "Python", "Cloud Systems"],
                "country": "India / Remote",
            },
        ]

    async def fetch_opportunities(self, limit: int = 20) -> List[RawOpportunity]:
        opportunities: List[RawOpportunity] = []
        for item in self.target_startups:
            company_info = CompanyInfo(
                name=item["name"],
                domain=item.get("domain"),
                website=item.get("website"),
                stage=item.get("stage", "seed"),
                source="Watchlist",
                description=item.get("description"),
                tech_stack=item.get("tech_stack", []),
                country=item.get("country", "Remote"),
            )

            opp = RawOpportunity(
                source=self.source_name,
                type=OpportunityType.FOUNDER_REACHOUT,
                title=f"{item['name']} — Core Outreach Target",
                url=item.get("website", f"https://{item.get('domain')}"),
                company=company_info,
                location=item.get("country", "Remote"),
                is_remote=True,
                raw_content=item.get("description"),
            )
            opportunities.append(opp)
            if len(opportunities) >= limit:
                break

        return opportunities
