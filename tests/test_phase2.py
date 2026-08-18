"""Unit tests for Phase 2: Multi-Source Discovery Connectors & Coordinator."""

import gc
import tempfile
from pathlib import Path
import pytest

from db.database import init_db, is_company_contacted_recently, record_sent_email
from discovery.manager import DiscoveryManager
from discovery.models import CompanyInfo, DiscoverySource, OpportunityType, RawOpportunity
from discovery.watchlist import WatchlistConnector


@pytest.fixture
def temp_db():
    """Create a fresh temporary SQLite database."""
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db_path = Path(f.name)
    init_db(db_path)
    yield db_path
    gc.collect()
    try:
        if db_path.exists():
            db_path.unlink()
        wal = db_path.with_suffix(".db-wal")
        shm = db_path.with_suffix(".db-shm")
        if wal.exists():
            wal.unlink()
        if shm.exists():
            shm.unlink()
    except (PermissionError, OSError):
        pass


@pytest.mark.asyncio
async def test_watchlist_connector():
    """Test watchlist connector returns curated startups."""
    connector = WatchlistConnector()
    opps = await connector.fetch_opportunities(limit=5)
    assert len(opps) > 0
    assert any(o.company.name == "Cursor" for o in opps)
    assert any(o.company.name == "Linear" for o in opps)


@pytest.mark.asyncio
async def test_discovery_manager_ingestion(temp_db):
    """Test discovery coordinator ingestion and deduplication."""
    manager = DiscoveryManager(db_path=temp_db)

    raw_items = [
        RawOpportunity(
            source=DiscoverySource.YC_DIRECTORY,
            type=OpportunityType.FOUNDER_REACHOUT,
            title="MorphAI (YC W25) - Code generation agents",
            url="https://ycombinator.com/companies/morphai",
            company=CompanyInfo(
                name="MorphAI",
                domain="morphai.dev",
                website="https://morphai.dev",
                stage="seed",
                source="YC W25",
                description="Code generation agents",
                country="Remote",
            ),
        ),
        RawOpportunity(
            source=DiscoverySource.ASHBY,
            type=OpportunityType.JOB_POSTING,
            title="Senior Backend Systems Engineer",
            url="https://jobs.ashbyhq.com/linear/123",
            company=CompanyInfo(
                name="Linear",
                domain="linear.app",
                website="https://linear.app",
                stage="series_b",
                source="Ashby",
            ),
        ),
    ]

    new_ids = await manager.ingest_opportunities(raw_items)
    assert len(new_ids) == 2

    # Ingesting same raw items again should return 0 new IDs (deduplication)
    dup_ids = await manager.ingest_opportunities(raw_items)
    assert len(dup_ids) == 0


@pytest.mark.asyncio
async def test_90_day_cooldown(temp_db):
    """Test that companies contacted within 90 days are skipped."""
    manager = DiscoveryManager(db_path=temp_db)

    item = RawOpportunity(
        source=DiscoverySource.WATCHLIST,
        type=OpportunityType.FOUNDER_REACHOUT,
        title="Tavily AI Reachout",
        url="https://tavily.com/launch",
        company=CompanyInfo(
            name="Tavily",
            domain="tavily.com",
            website="https://tavily.com",
            stage="seed",
            source="Watchlist",
        ),
    )

    # First ingest
    new_ids = await manager.ingest_opportunities([item])
    assert len(new_ids) == 1
    opp_id = new_ids[0]

    # Record email sent
    record_sent_email(
        opportunity_id=opp_id,
        draft_id=None,
        contact_id=None,
        recipient_email="founder@tavily.com",
        subject="Connecting",
        body="Intro body",
        db_path=temp_db,
    )

    # Another opportunity from same company should be skipped due to cooldown
    item2 = RawOpportunity(
        source=DiscoverySource.ASHBY,
        type=OpportunityType.JOB_POSTING,
        title="New Job at Tavily",
        url="https://jobs.ashbyhq.com/tavily/456",
        company=CompanyInfo(
            name="Tavily",
            domain="tavily.com",
            website="https://tavily.com",
            stage="seed",
            source="Ashby",
        ),
    )

    skipped_ids = await manager.ingest_opportunities([item2])
    assert len(skipped_ids) == 0
