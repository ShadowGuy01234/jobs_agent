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


@pytest.mark.asyncio
async def test_hunter_discover_connector_mock(monkeypatch):
    """Test HunterDiscoverConnector parses /v2/discover results and homepage summary."""
    from unittest.mock import MagicMock
    import httpx
    from discovery.company_launch.hunter_discover import HunterDiscoverConnector

    class FakeClient:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return False

        async def post(self, url, **kwargs):
            resp = MagicMock()
            resp.status_code = 200
            resp.json.return_value = {
                "data": [
                    {
                        "domain": "scalekit.com",
                        "organization": "Scalekit",
                        "emails_count": {"personal": 15, "generic": 10, "total": 25},
                    },
                    {
                        "domain": "emptyco.io",
                        "organization": "EmptyCo",
                        "emails_count": {"personal": 0, "generic": 1, "total": 1},
                    },
                ]
            }
            return resp

        async def get(self, url, **kwargs):
            resp = MagicMock()
            resp.status_code = 200
            resp.text = (
                "<html><head><title>Scalekit | Auth for AI Agents</title>"
                '<meta name="description" content="Enterprise auth stack for AI apps.">'
                '</head><body><a href="/careers">Careers</a></body></html>'
            )
            return resp

    monkeypatch.setattr(httpx, "AsyncClient", FakeClient)

    connector = HunterDiscoverConnector(api_key="test-hunter-key")
    opps = await connector.fetch_opportunities(limit=5)
    assert len(opps) == 1
    assert opps[0].source == DiscoverySource.HUNTER_DISCOVER
    assert opps[0].company.domain == "scalekit.com"
    assert opps[0].company.name == "Scalekit"
    assert "Auth for AI Agents" in opps[0].raw_content
    assert "/careers" in opps[0].raw_content


@pytest.mark.asyncio
async def test_github_trending_connector_mock(monkeypatch):
    """Test GitHubTrendingConnector extracts startup orgs and skips awesome-list noise."""
    from unittest.mock import MagicMock
    import httpx
    from discovery.company_launch.github_trending import GitHubTrendingConnector

    class FakeClient:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return False

        async def get(self, url, **kwargs):
            resp = MagicMock()
            resp.status_code = 200
            resp.json.return_value = {
                "items": [
                    {
                        "id": 1,
                        "name": "awesome-ai-agents",
                        "full_name": "user/awesome-ai-agents",
                        "homepage": "https://example.com",
                        "stargazers_count": 5000,
                        "owner": {"login": "user", "type": "User"},
                    },
                    {
                        "id": 2,
                        "name": "agent-runtime",
                        "full_name": "acme-ai/agent-runtime",
                        "homepage": "https://acme-ai.dev",
                        "description": "Fast Rust/Python agent runtime",
                        "language": "Python",
                        "topics": ["ai-agents", "langgraph"],
                        "stargazers_count": 820,
                        "html_url": "https://github.com/acme-ai/agent-runtime",
                        "owner": {"login": "acme-ai", "type": "Organization"},
                    },
                ]
            }
            return resp

    monkeypatch.setattr(httpx, "AsyncClient", FakeClient)

    connector = GitHubTrendingConnector()
    opps = await connector.fetch_opportunities(limit=5)
    assert len(opps) == 1
    assert opps[0].source == DiscoverySource.GITHUB_TRENDING
    assert opps[0].company.domain == "acme-ai.dev"
    assert opps[0].company.name == "acme-ai"


@pytest.mark.asyncio
async def test_remote_boards_isolates_failing_feed(monkeypatch):
    """One failing/timing-out feed must not block results from healthy remote feeds."""
    from discovery.job_boards.remote_boards import RemoteBoardsConnector

    connector = RemoteBoardsConnector(feeds=["remoteok", "remotive"])

    async def fake_fetch(client, name):
        if name == "remoteok":
            raise TimeoutError("simulated connect timeout")
        return [
            ("Senior AI Engineer", "AcmeAI", "https://remotive.com/jobs/1", "Remote", True, "Python LangGraph")
        ]

    monkeypatch.setattr(connector, "_fetch_feed", fake_fetch)
    opps = await connector.fetch_opportunities(limit=10)
    assert len(opps) == 1
    assert opps[0].company.name == "AcmeAI"
