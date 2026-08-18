"""Discovery Coordinator: orchestrates all connectors, deduplicates against SQLite, and queues new opportunities."""

import asyncio
import logging
from pathlib import Path
from typing import Dict, List, Optional

from config import settings
from db.database import (
    get_or_create_company,
    is_company_contacted_recently,
    log_audit,
    opportunity_exists,
    save_opportunity,
)
from discovery.base import BaseDiscoveryConnector
from discovery.company_launch import (
    HackerNewsConnector,
    IndianStartupsConnector,
    ProductHuntConnector,
    SecEdgarConnector,
    TavilyStealthConnector,
    VCStealthConnector,
    YCDirectoryConnector,
)
from discovery.job_boards import AshbyConnector, GreenhouseConnector, LeverConnector
from discovery.models import DiscoverySource, RawOpportunity
from discovery.watchlist import WatchlistConnector

logger = logging.getLogger(__name__)


class DiscoveryManager:
    """Manages execution of discovery connectors with deduplication and throttling."""

    def __init__(self, db_path: Optional[Path] = None):
        self.db_path = db_path or settings.DATABASE_PATH
        self.connectors: Dict[str, BaseDiscoveryConnector] = {
            # Track A: Job Boards
            "ashby": AshbyConnector(),
            "greenhouse": GreenhouseConnector(),
            "lever": LeverConnector(),
            # Track B: Launches, Stealth & Feeds
            "yc": YCDirectoryConnector(),
            "producthunt": ProductHuntConnector(),
            "hackernews": HackerNewsConnector(),
            "india": IndianStartupsConnector(),
            "sec_edgar": SecEdgarConnector(),
            "vc_stealth": VCStealthConnector(),
            "tavily_stealth": TavilyStealthConnector(),
            "watchlist": WatchlistConnector(),
        }

    async def run_connector(
        self, name: str, limit: int = 20
    ) -> List[RawOpportunity]:
        """Run a single discovery connector by name."""
        connector = self.connectors.get(name.lower())
        if not connector:
            logger.warning(f"Connector '{name}' not found. Available: {list(self.connectors.keys())}")
            return []

        logger.info(f"Running discovery connector: {name}")
        try:
            return await connector.fetch_opportunities(limit=limit)
        except Exception as e:
            logger.error(f"Error running connector {name}: {e}", exc_info=True)
            return []

    async def ingest_opportunities(
        self, raw_items: List[RawOpportunity]
    ) -> List[int]:
        """Deduplicate and store raw opportunities into SQLite. Returns new opportunity IDs."""
        new_opp_ids: List[int] = []

        for item in raw_items:
            # 1. Check if opportunity URL already exists
            if opportunity_exists(item.url, self.db_path):
                logger.debug(f"Skipping existing opportunity URL: {item.url}")
                continue

            # 2. Get or create company
            company_id = get_or_create_company(
                domain=item.company.domain,
                name=item.company.name,
                website=item.company.website,
                stage=item.company.stage,
                source=item.source.value,
                description=item.company.description,
                tech_stack=item.company.tech_stack,
                funding_info=item.company.funding_info,
                country=item.company.country,
                is_stealth=item.company.is_stealth,
                db_path=self.db_path,
            )

            # 3. Check 90-day cooldown on already-contacted companies
            if is_company_contacted_recently(company_id, days=90, db_path=self.db_path):
                logger.info(f"Skipping {item.company.name} — reached out within last 90 days.")
                continue

            # 4. Save new opportunity record
            opp_id = save_opportunity(
                company_id=company_id,
                type_=item.type.value,
                title=item.title,
                url=item.url,
                external_id=item.external_id,
                location=item.location,
                is_remote=item.is_remote,
                raw_content=item.raw_content,
                status="discovered",
                db_path=self.db_path,
            )

            if opp_id:
                new_opp_ids.append(opp_id)
                logger.info(f"Ingested new opportunity [{opp_id}]: {item.title} ({item.company.name})")

        log_audit(
            event_type="discovery_ingest",
            message=f"Ingested {len(new_opp_ids)} new opportunities from batch of {len(raw_items)}",
            payload={"new_opportunity_ids": new_opp_ids},
            db_path=self.db_path,
        )

        return new_opp_ids

    async def run_discovery_sweep(
        self, sources: Optional[List[str]] = None, limit_per_source: int = 15
    ) -> List[int]:
        """Run multiple connectors concurrently and ingest discoveries."""
        target_sources = sources or list(self.connectors.keys())
        tasks = [self.run_connector(src, limit=limit_per_source) for src in target_sources]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        all_raw_items: List[RawOpportunity] = []
        for src_name, res in zip(target_sources, results):
            if isinstance(res, Exception):
                logger.error(f"Connector {src_name} failed: {res}")
            elif isinstance(res, list):
                all_raw_items.extend(res)

        new_ids = await self.ingest_opportunities(all_raw_items)
        return new_ids
