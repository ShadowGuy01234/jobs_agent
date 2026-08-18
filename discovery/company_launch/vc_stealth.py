"""VC Portfolio Stealth announcements and funding feeds connector."""

import logging
from typing import List, Optional
import feedparser
from bs4 import BeautifulSoup

from discovery.base import BaseDiscoveryConnector
from discovery.models import CompanyInfo, DiscoverySource, OpportunityType, RawOpportunity

logger = logging.getLogger(__name__)


class VCStealthConnector(BaseDiscoveryConnector):
    source_name = DiscoverySource.VC_STEALTH

    def __init__(self, rss_feeds: Optional[List[str]] = None):
        self.rss_feeds = rss_feeds or [
            "https://techcrunch.com/category/startups/feed/",
            "https://venturebeat.com/category/ai/feed/",
            "https://strictlyvc.com/feed/",
        ]

    async def fetch_opportunities(self, limit: int = 20) -> List[RawOpportunity]:
        opportunities: List[RawOpportunity] = []

        try:
            for feed_url in self.rss_feeds:
                feed = feedparser.parse(feed_url)
                for entry in feed.entries:
                    title = entry.get("title", "")
                    summary_html = entry.get("summary", "")
                    clean_summary = BeautifulSoup(summary_html, "html.parser").get_text().strip() if summary_html else ""
                    combined_text = f"{title} {clean_summary}".lower()

                    # Detect stealth / pre-seed / seed funding announcements
                    is_stealth = "stealth" in combined_text
                    is_funding = any(k in combined_text for k in ["raises", "seed round", "pre-seed", "funding", "emerges from stealth", "backed by"])

                    if not (is_stealth or is_funding):
                        continue

                    link = entry.get("link", "")
                    # Extract company name from title
                    company_name = title.split("raises")[0].split("secures")[0].split("emerges")[0].split("bags")[0].split("—")[0].split("-")[0].strip()

                    company_info = CompanyInfo(
                        name=company_name,
                        domain=None,
                        website=link,
                        stage="pre_seed" if is_stealth else "seed",
                        source="VC & Tech News",
                        description=clean_summary or title,
                        funding_info=title,
                        is_stealth=is_stealth,
                    )

                    opp = RawOpportunity(
                        source=self.source_name,
                        type=OpportunityType.STEALTH_REACHOUT if is_stealth else OpportunityType.FOUNDER_REACHOUT,
                        title=f"{title} ({'Stealth' if is_stealth else 'Funded'})",
                        url=link,
                        company=company_info,
                        external_id=entry.get("id", link),
                        location="Remote",
                        is_remote=True,
                        raw_content=clean_summary or title,
                        metadata={"source_feed": feed_url},
                    )
                    opportunities.append(opp)
                    if len(opportunities) >= limit:
                        return opportunities

        except Exception as e:
            logger.warning(f"Error fetching VC stealth news: {e}")

        return opportunities[:limit]
