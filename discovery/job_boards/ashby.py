"""Ashby public job posting API connector."""

import logging
from typing import List, Optional
import httpx
from bs4 import BeautifulSoup

from discovery.base import BaseDiscoveryConnector
from discovery.models import CompanyInfo, DiscoverySource, OpportunityType, RawOpportunity

logger = logging.getLogger(__name__)


class AshbyConnector(BaseDiscoveryConnector):
    source_name = DiscoverySource.ASHBY

    def __init__(self, target_boards: Optional[List[str]] = None):
        # Default top AI/tech startups known to use Ashby
        self.target_boards = target_boards or [
            "linear",
            "cursor",
            "perplextiy",
            "tavily",
            "replit",
            "cohere",
            "sentry",
            "together-ai",
            "modal",
            "langfuse",
        ]

    async def fetch_board_jobs(self, board_slug: str) -> List[RawOpportunity]:
        url = f"https://api.ashbyhq.com/posting-api/job-board/{board_slug}"
        opportunities: List[RawOpportunity] = []

        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                resp = await client.get(url)
                if resp.status_code != 200:
                    logger.debug(f"Ashby board {board_slug} returned HTTP {resp.status_code}")
                    return []

                data = resp.json()
                jobs = data.get("jobs", [])
                company_name = data.get("name", board_slug.capitalize())

                company_info = CompanyInfo(
                    name=company_name,
                    domain=f"{board_slug}.com",
                    website=f"https://{board_slug}.com",
                    stage="series_a",
                    source=self.source_name.value,
                )

                for job in jobs:
                    if not job.get("isListed", True):
                        continue

                    title = job.get("title", "")
                    job_url = job.get("jobUrl", f"https://jobs.ashbyhq.com/{board_slug}/{job.get('id')}")
                    location = job.get("location", "Remote")
                    is_remote = job.get("isRemote", True) or "remote" in location.lower()
                    desc_html = job.get("descriptionHtml", "")
                    clean_desc = BeautifulSoup(desc_html, "html.parser").get_text(separator="\n").strip() if desc_html else ""

                    opp = RawOpportunity(
                        source=self.source_name,
                        type=OpportunityType.JOB_POSTING,
                        title=title,
                        url=job_url,
                        company=company_info,
                        external_id=str(job.get("id")),
                        location=location,
                        is_remote=is_remote,
                        raw_content=clean_desc,
                        metadata={
                            "department": job.get("department"),
                            "employmentType": job.get("employmentType"),
                        },
                    )
                    opportunities.append(opp)

        except Exception as e:
            logger.warning(f"Error fetching Ashby board {board_slug}: {e}")

        return opportunities

    async def fetch_opportunities(self, limit: int = 50) -> List[RawOpportunity]:
        all_opps: List[RawOpportunity] = []
        for board in self.target_boards:
            opps = await self.fetch_board_jobs(board)
            all_opps.extend(opps)
            if len(all_opps) >= limit:
                break
        return all_opps[:limit]
