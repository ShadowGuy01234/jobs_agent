"""GitHub Trending / Fast-Growing AI & DevTools Startups connector (keyless public API)."""

import logging
from datetime import datetime, timedelta, timezone
from typing import List, Optional
from urllib.parse import urlparse

import httpx

from discovery.base import BaseDiscoveryConnector
from discovery.models import CompanyInfo, DiscoverySource, OpportunityType, RawOpportunity

logger = logging.getLogger(__name__)

GITHUB_REPO_SEARCH_URL = "https://api.github.com/search/repositories"

DEFAULT_QUERIES = [
    "topic:ai-agents stars:80..8000 fork:false",
    "topic:llm stars:80..8000 fork:false",
    "topic:developer-tools stars:80..8000 fork:false",
]

_BLOCKED_HOMEPAGE_HOSTS = (
    "github.com",
    "github.io",
    "youtube.com",
    "youtu.be",
    "twitter.com",
    "x.com",
    "medium.com",
    "arxiv.org",
    "pypi.org",
    "npmjs.com",
    "huggingface.co",
    "discord.gg",
    "discord.com",
)
_NOISE_REPO_TERMS = ("awesome-", "tutorial", "course", "roadmap", "interview", "cheatsheet", "books", "-guide")


def _extract_domain(url: str) -> Optional[str]:
    if not url:
        return None
    parsed = urlparse(url if "://" in url else f"https://{url}")
    host = (parsed.netloc or "").lower().removeprefix("www.")
    if not host or "." not in host or any(b in host for b in _BLOCKED_HOMEPAGE_HOSTS):
        return None
    return host


class GitHubTrendingConnector(BaseDiscoveryConnector):
    """Discover fast-growing AI/DevTools projects & startup orgs from GitHub Search API."""

    source_name = DiscoverySource.GITHUB_TRENDING

    def __init__(self, queries: Optional[List[str]] = None):
        self.queries = queries or DEFAULT_QUERIES
        self._query_index = 0

    async def fetch_opportunities(self, limit: int = 15) -> List[RawOpportunity]:
        now = datetime.now(timezone.utc)
        created_cutoff = (now - timedelta(days=365)).strftime("%Y-%m-%d")
        pushed_cutoff = (now - timedelta(days=30)).strftime("%Y-%m-%d")
        base_q = self.queries[self._query_index % len(self.queries)]
        self._query_index += 1
        query = f"{base_q} created:>={created_cutoff} pushed:>={pushed_cutoff}"

        headers = {
            "Accept": "application/vnd.github+json",
            "User-Agent": "job-outreach-agent/1.0",
        }

        opportunities: List[RawOpportunity] = []
        seen_domains: set[str] = set()

        try:
            async with httpx.AsyncClient(timeout=15.0, headers=headers) as client:
                resp = await client.get(
                    GITHUB_REPO_SEARCH_URL,
                    params={"q": query, "sort": "stars", "order": "desc", "per_page": min(limit * 3, 40)},
                )
                if resp.status_code != 200:
                    logger.warning(f"GitHub search returned HTTP {resp.status_code}")
                    return []

                for repo in resp.json().get("items", []):
                    name = (repo.get("name") or "").strip()
                    full_name = (repo.get("full_name") or "").strip()
                    if not name or any(t in name.lower() for t in _NOISE_REPO_TERMS):
                        continue

                    homepage = (repo.get("homepage") or "").strip()
                    domain = _extract_domain(homepage)
                    # Prefer projects/orgs with an actual product website
                    if not domain or domain in seen_domains:
                        continue
                    seen_domains.add(domain)

                    owner = repo.get("owner") or {}
                    owner_login = (owner.get("login") or name).strip()
                    owner_type = owner.get("type", "User")
                    display_name = owner_login if owner_type == "Organization" else name
                    desc = (repo.get("description") or "").strip()
                    topics = [t for t in (repo.get("topics") or []) if t][:6]
                    stars = int(repo.get("stargazers_count") or 0)
                    html_url = repo.get("html_url") or f"https://{domain}"

                    company_info = CompanyInfo(
                        name=display_name,
                        domain=domain,
                        website=f"https://{domain}",
                        stage="seed",
                        description=desc[:400] or f"Open-source project {full_name}",
                        tech_stack=topics or ([repo["language"]] if repo.get("language") else []),
                        funding_info=f"GitHub {stars:,} stars ({full_name})",
                        country="Remote",
                        is_stealth=False,
                    )

                    opportunities.append(
                        RawOpportunity(
                            source=self.source_name,
                            type=OpportunityType.FOUNDER_REACHOUT,
                            title=f"{display_name} ({full_name}, {stars:,}★) — {desc[:90]}",
                            url=html_url,
                            company=company_info,
                            external_id=str(repo.get("id") or full_name),
                            location="Remote",
                            is_remote=True,
                            raw_content=f"{full_name} ({stars:,} stars, language: {repo.get('language')}). {desc}".strip(),
                            metadata={"stars": stars, "topics": topics, "owner_type": owner_type},
                        )
                    )
                    if len(opportunities) >= limit:
                        break
        except Exception as e:
            logger.warning(f"Error fetching GitHub trending repos: {e}")

        return opportunities[:limit]
