"""SEC Form D filings connector for stealth startup funding rounds."""

import logging
from typing import List, Optional
import feedparser
import httpx
from bs4 import BeautifulSoup

from discovery.base import BaseDiscoveryConnector
from discovery.models import CompanyInfo, DiscoverySource, OpportunityType, RawOpportunity

logger = logging.getLogger(__name__)


class SecEdgarConnector(BaseDiscoveryConnector):
    source_name = DiscoverySource.SEC_EDGAR

    def __init__(self, user_agent: str = "PersonalJobOutreachBot/1.0 (contact@personaloutreach.local)"):
        # SEC EDGAR requires a custom User-Agent header
        self.user_agent = user_agent
        self.atom_url = "https://www.sec.gov/cgi-bin/browse-edgar?action=getcurrent&type=D&company=&dateb=&owner=include&start=0&count=40&output=atom"

    async def fetch_opportunities(self, limit: int = 20) -> List[RawOpportunity]:
        opportunities: List[RawOpportunity] = []
        headers = {"User-Agent": self.user_agent}

        try:
            async with httpx.AsyncClient(timeout=15.0, headers=headers) as client:
                resp = await client.get(self.atom_url)
                if resp.status_code != 200:
                    logger.debug(f"SEC EDGAR returned HTTP {resp.status_code}")
                    return []

                feed = feedparser.parse(resp.text)
                for entry in feed.entries:
                    title = entry.get("title", "")
                    # SEC title format: "D - Company Name (0001234567) (Filer)"
                    if not title.startswith("D -"):
                        continue

                    raw_company_name = title.replace("D -", "").split("(")[0].strip()
                    # Filter out obvious non-tech (e.g. real estate funds, oil, mining)
                    if any(x in raw_company_name.lower() for x in ["real estate", "oil", "gas", "mining", "lp", "fund i", "fund ii", "capital management"]):
                        continue

                    link = entry.get("link", "")
                    summary = entry.get("summary", "")
                    clean_summary = BeautifulSoup(summary, "html.parser").get_text().strip() if summary else ""

                    company_info = CompanyInfo(
                        name=raw_company_name,
                        domain=None,
                        website=None,
                        stage="pre_seed",
                        source="SEC Form D",
                        description=f"Stealth funding filing: {raw_company_name} filed Form D with SEC.",
                        funding_info="SEC Form D Exempt Offering",
                        country="United States",
                        is_stealth=True,
                    )

                    opp = RawOpportunity(
                        source=self.source_name,
                        type=OpportunityType.STEALTH_REACHOUT,
                        title=f"{raw_company_name} (Stealth SEC Form D Filing)",
                        url=link,
                        company=company_info,
                        external_id=entry.get("id", link),
                        location="US / Remote",
                        is_remote=True,
                        raw_content=f"{raw_company_name} recently filed SEC Form D for an exempt offering round. {clean_summary}",
                        metadata={"filing_type": "Form D"},
                    )
                    opportunities.append(opp)
                    if len(opportunities) >= limit:
                        break

        except Exception as e:
            logger.warning(f"Error fetching SEC Form D filings: {e}")

        return opportunities
