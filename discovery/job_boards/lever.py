"""Lever public job posting API connector."""

import logging
from typing import List, Optional
import httpx

from discovery.base import BaseDiscoveryConnector
from discovery.models import CompanyInfo, DiscoverySource, OpportunityType, RawOpportunity
from pipeline.nodes.score_fit import check_title_relevance

logger = logging.getLogger(__name__)


class LeverConnector(BaseDiscoveryConnector):
    source_name = DiscoverySource.LEVER

    def __init__(self, target_companies: Optional[List[str]] = None):
        self.target_companies = target_companies or [
            "dbtlabs",
            "atlassian",
            "vercel",
            "pinecone",
            "deepgram",
            "sourcegraph",
            "hasura",
        ]

    async def fetch_company_jobs(self, company_slug: str) -> List[RawOpportunity]:
        url = f"https://api.lever.co/v0/postings/{company_slug}?mode=json"
        opportunities: List[RawOpportunity] = []

        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                resp = await client.get(url)
                if resp.status_code != 200:
                    logger.debug(f"Lever company {company_slug} returned HTTP {resp.status_code}")
                    return []

                postings = resp.json()
                company_info = CompanyInfo(
                    name=company_slug.capitalize(),
                    domain=f"{company_slug}.com",
                    website=f"https://{company_slug}.com",
                    stage="series_a",
                    source=self.source_name.value,
                )

                for post in postings:
                    title = post.get("text", "")
                    # Skip non-engineering roles here so `limit` counts relevant jobs.
                    if check_title_relevance(title, OpportunityType.JOB_POSTING.value):
                        continue
                    job_url = post.get("hostedUrl", "")
                    categories = post.get("categories", {})
                    location = categories.get("location", "Remote")
                    workplace_type = post.get("workplaceType", "")
                    is_remote = workplace_type == "remote" or "remote" in location.lower()
                    desc_plain = post.get("descriptionPlain", "")

                    opp = RawOpportunity(
                        source=self.source_name,
                        type=OpportunityType.JOB_POSTING,
                        title=title,
                        url=job_url,
                        company=company_info,
                        external_id=str(post.get("id")),
                        location=location,
                        is_remote=is_remote,
                        raw_content=desc_plain,
                    )
                    opportunities.append(opp)

        except Exception as e:
            logger.warning(f"Error fetching Lever company {company_slug}: {e}")

        return opportunities

    async def fetch_opportunities(self, limit: int = 50) -> List[RawOpportunity]:
        all_opps: List[RawOpportunity] = []
        for company in self.target_companies:
            opps = await self.fetch_company_jobs(company)
            all_opps.extend(opps)
            if len(all_opps) >= limit:
                break
        return all_opps[:limit]
