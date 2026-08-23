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
from discovery.board_tokens import merge_board_tokens
from discovery.company_launch import (
    HackerNewsConnector,
    HNHiringConnector,
    IndianStartupsConnector,
    ProductHuntConnector,
    SecEdgarConnector,
    TavilyStealthConnector,
    VCStealthConnector,
    YCDirectoryConnector,
)
from discovery.job_boards import (
    AshbyConnector,
    GreenhouseConnector,
    LeverConnector,
    RemoteBoardsConnector,
)
from discovery.models import DiscoverySource, RawOpportunity
from discovery.watchlist import WatchlistConnector
from pipeline.nodes.score_fit import check_title_relevance
from profile.models import DiscoveryTargets
from profile.parser import load_user_profile

logger = logging.getLogger(__name__)


class DiscoveryManager:
    """Manages execution of discovery connectors with deduplication and throttling."""

    def __init__(self, db_path: Optional[Path] = None):
        self.db_path = db_path or settings.DATABASE_PATH

        # Target lists come from user_profile.yaml so retargeting needs no code edit.
        # An empty list means "use the connector's own defaults", so `or None` is load-bearing.
        try:
            targets = load_user_profile().discovery
        except Exception as e:
            logger.warning(f"Could not load discovery targets from profile ({e}); using connector defaults.")
            targets = DiscoveryTargets()

        self.connectors: Dict[str, BaseDiscoveryConnector] = {
            # Track A: Job Boards
            "ashby": AshbyConnector(target_boards=merge_board_tokens("ashby", targets.ashby_boards)),
            "greenhouse": GreenhouseConnector(target_boards=merge_board_tokens("greenhouse", targets.greenhouse_boards)),
            "lever": LeverConnector(target_companies=merge_board_tokens("lever", targets.lever_boards)),
            "remote_boards": RemoteBoardsConnector(),
            # Track B: Launches, Stealth & Feeds
            "yc": YCDirectoryConnector(batches=targets.yc_batches or None),
            "producthunt": ProductHuntConnector(),
            "hackernews": HackerNewsConnector(queries=targets.hn_queries or None),
            "hn_hiring": HNHiringConnector(),
            "india": IndianStartupsConnector(rss_feeds=targets.india_rss or None),
            "sec_edgar": SecEdgarConnector(),
            "vc_stealth": VCStealthConnector(rss_feeds=targets.vc_rss or None),
            "tavily_stealth": TavilyStealthConnector(),
            "watchlist": WatchlistConnector(target_startups=targets.watchlist or None),
        }

    async def run_connector(
        self, name: str, limit: int = 20
    ) -> List[RawOpportunity]:
        """Run a single discovery connector by name."""
        connector = self.connectors.get(name.lower())
        if not connector:
            # Raise rather than return []: a silent empty result let a misspelled source name
            # ("tavily" vs "tavily_stealth") sit undetected in the hourly rotation indefinitely.
            raise ValueError(
                f"Unknown discovery source '{name}'. Available: {sorted(self.connectors)}"
            )

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

        skipped_titles = 0

        for item in raw_items:
            # 0. Drop non-engineering job titles before they reach SQLite at all. Guarding here
            # rather than in each connector covers every source at once, and keeps irrelevant
            # rows from occupying the hourly sweep's limited unscored-backlog slots.
            title_reason = check_title_relevance(item.title, item.type.value)
            if title_reason:
                logger.debug(f"Skipping irrelevant opportunity: {title_reason}")
                skipped_titles += 1
                continue

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

        if skipped_titles:
            logger.info(f"Filtered {skipped_titles} non-engineering title(s) before ingest.")

        log_audit(
            event_type="discovery_ingest",
            message=f"Ingested {len(new_opp_ids)} new opportunities from batch of {len(raw_items)} "
                    f"({skipped_titles} filtered on title)",
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
