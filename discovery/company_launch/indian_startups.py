"""Indian tech startup ecosystem and funding news connector."""

import logging
from typing import List, Optional
import feedparser
from bs4 import BeautifulSoup

from discovery.base import BaseDiscoveryConnector
from discovery.models import CompanyInfo, DiscoverySource, OpportunityType, RawOpportunity

logger = logging.getLogger(__name__)


class IndianStartupsConnector(BaseDiscoveryConnector):
    source_name = DiscoverySource.INDIAN_STARTUPS

    def __init__(self, rss_feeds: Optional[List[str]] = None):
        self.rss_feeds = rss_feeds or [
            "https://inc42.com/category/startups/feed/",
            "https://entrackr.com/feed/",
            "https://yourstory.com/feed",
        ]

    async def fetch_opportunities(self, limit: int = 25) -> List[RawOpportunity]:
        opportunities: List[RawOpportunity] = []

        try:
            for feed_url in self.rss_feeds:
                feed = feedparser.parse(feed_url)
                for entry in feed.entries:
                    title = entry.get("title", "")
                    # Look for funding / launch / seed announcements in Indian tech news
                    lower_title = title.lower()
                    # Skip macro industry roundup articles that are not about a specific startup
                    if any(noise in lower_title for noise in [
                        "funding report", "nearly doubles", "total funding", "funding boom",
                        "top 10", "top 5", "this week", "year in review", "startup ecosystem",
                        "india ai funding", "funding in ",
                    ]):
                        continue
                    if not any(k in lower_title for k in ["raises", "secures", "bags", "closes", "seed", "series a"]):
                        continue

                    link = entry.get("link", "")
                    summary_html = entry.get("summary", "")
                    clean_summary = BeautifulSoup(summary_html, "html.parser").get_text(separator="\n").strip() if summary_html else ""

                    # Extract company name from headline (e.g. "AI startup Sarvam raises $41M" or "Krutrim secures seed")
                    words = title.split()
                    company_name = ""
                    for idx, w in enumerate(words):
                        if w.lower() in ["raises", "secures", "bags", "gets", "closes"] and idx > 0:
                            company_name = " ".join(words[:idx]).replace("Startup", "").replace("AI startup", "").replace("Fintech", "").strip()
                            break
                    if not company_name or len(company_name.split()) > 6:
                        continue

                    company_info = CompanyInfo(
                        name=company_name,
                        domain=None,
                        website=link,
                        stage="seed",
                        source="Indian Tech Media",
                        description=clean_summary or title,
                        funding_info=title,
                        country="India",
                        is_stealth=False,
                    )

                    opp = RawOpportunity(
                        source=self.source_name,
                        type=OpportunityType.FOUNDER_REACHOUT,
                        title=f"{title} (India Tech)",
                        url=link,
                        company=company_info,
                        external_id=entry.get("id", link),
                        location="India / Remote",
                        is_remote=True,
                        raw_content=clean_summary or title,
                        metadata={"source_feed": feed_url},
                    )
                    opportunities.append(opp)
                    if len(opportunities) >= limit:
                        return opportunities

        except Exception as e:
            logger.warning(f"Error fetching Indian startups RSS: {e}")

        return opportunities[:limit]
