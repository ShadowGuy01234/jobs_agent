"""Product Hunt launches connector using RSS feeds."""

import logging
from typing import List
import feedparser
from bs4 import BeautifulSoup

from discovery.base import BaseDiscoveryConnector
from discovery.models import CompanyInfo, DiscoverySource, OpportunityType, RawOpportunity

logger = logging.getLogger(__name__)


class ProductHuntConnector(BaseDiscoveryConnector):
    source_name = DiscoverySource.PRODUCT_HUNT

    def __init__(self, rss_url: str = "https://www.producthunt.com/feed"):
        self.rss_url = rss_url

    async def fetch_opportunities(self, limit: int = 20) -> List[RawOpportunity]:
        opportunities: List[RawOpportunity] = []
        try:
            feed = feedparser.parse(self.rss_url)
            for entry in feed.entries:
                title = entry.get("title", "")
                link = entry.get("link", "")
                summary_html = entry.get("summary", "")
                clean_summary = BeautifulSoup(summary_html, "html.parser").get_text(separator="\n").strip() if summary_html else ""

                # Extract company name from title (e.g. "Cursor - AI code editor")
                company_name = title.split("-")[0].split("—")[0].split(":")[0].strip()
                domain = f"{company_name.lower().replace(' ', '')}.com"

                company_info = CompanyInfo(
                    name=company_name,
                    domain=domain,
                    website=link,
                    stage="pre_seed",
                    source="Product Hunt",
                    description=clean_summary,
                )

                opp = RawOpportunity(
                    source=self.source_name,
                    type=OpportunityType.FOUNDER_REACHOUT,
                    title=f"{title} (Product Hunt Launch)",
                    url=link,
                    company=company_info,
                    external_id=entry.get("id", link),
                    location="Remote",
                    is_remote=True,
                    raw_content=clean_summary,
                    metadata={"published": entry.get("published")},
                )
                opportunities.append(opp)
                if len(opportunities) >= limit:
                    break

        except Exception as e:
            logger.warning(f"Error fetching Product Hunt RSS: {e}")

        return opportunities
