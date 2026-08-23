"""Greenhouse public job board connector."""

import logging
from typing import List, Optional
import httpx
from bs4 import BeautifulSoup

from discovery.base import BaseDiscoveryConnector
from discovery.models import CompanyInfo, DiscoverySource, OpportunityType, RawOpportunity
from pipeline.nodes.score_fit import check_title_relevance

logger = logging.getLogger(__name__)


class GreenhouseConnector(BaseDiscoveryConnector):
    source_name = DiscoverySource.GREENHOUSE

    def __init__(self, target_boards: Optional[List[str]] = None):
        self.target_boards = target_boards or [
            "stripe",
            "anthropic",
            "openai",
            "scaleai",
            "figma",
            "postman",
            "razorpay",
            "groww",
            "browserbase",
            "supabase",
        ]

    async def fetch_board_jobs(self, board_token: str) -> List[RawOpportunity]:
        url = f"https://boards-api.greenhouse.io/v1/boards/{board_token}/jobs?content=true"
        opportunities: List[RawOpportunity] = []

        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                resp = await client.get(url)
                if resp.status_code != 200:
                    logger.debug(f"Greenhouse board {board_token} returned HTTP {resp.status_code}")
                    return []

                data = resp.json()
                jobs = data.get("jobs", [])
                company_info = CompanyInfo(
                    name=board_token.capitalize(),
                    domain=f"{board_token}.com",
                    website=f"https://{board_token}.com",
                    stage="series_b",
                    source=self.source_name.value,
                )

                for job in jobs:
                    title = job.get("title", "")
                    # Skip non-engineering roles here so `limit` counts relevant jobs. A big
                    # board's sales openings would otherwise fill the whole per-sweep quota.
                    if check_title_relevance(title, OpportunityType.JOB_POSTING.value):
                        continue
                    job_url = job.get("absolute_url", "")
                    location_obj = job.get("location", {})
                    location_name = location_obj.get("name", "Remote") if isinstance(location_obj, dict) else str(location_obj)
                    is_remote = "remote" in location_name.lower() or "anywhere" in location_name.lower()

                    content_html = job.get("content", "")
                    clean_desc = BeautifulSoup(content_html, "html.parser").get_text(separator="\n").strip() if content_html else ""

                    opp = RawOpportunity(
                        source=self.source_name,
                        type=OpportunityType.JOB_POSTING,
                        title=title,
                        url=job_url,
                        company=company_info,
                        external_id=str(job.get("id")),
                        location=location_name,
                        is_remote=is_remote,
                        raw_content=clean_desc,
                    )
                    opportunities.append(opp)

        except Exception as e:
            logger.warning(f"Error fetching Greenhouse board {board_token}: {e}")

        return opportunities

    async def fetch_opportunities(self, limit: int = 50) -> List[RawOpportunity]:
        all_opps: List[RawOpportunity] = []
        for board in self.target_boards:
            opps = await self.fetch_board_jobs(board)
            all_opps.extend(opps)
            if len(all_opps) >= limit:
                break
        return all_opps[:limit]
