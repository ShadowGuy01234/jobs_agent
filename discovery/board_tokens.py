"""Job-board token discovery and cache.

The Greenhouse/Lever/Ashby connectors were each capped by a hand-typed list of ~10 slugs, so
the entire job-board funnel could only ever see those companies. This module grows that list
automatically: it derives candidate slugs from the YC companies the yc_directory connector
already fetches, probes the three public board APIs, and caches whichever ones are live.

No API keys, no scraping — just the same public endpoints the connectors already call.
"""

import asyncio
import json
import logging
import re
from pathlib import Path
from typing import Dict, Iterable, List, Optional

import httpx

from config import settings
from discovery.company_launch.yc_directory import fetch_recent_batches

logger = logging.getLogger(__name__)

CACHE_PATH: Path = settings.DATA_DIR / "board_tokens.json"

PROBE_URLS: Dict[str, str] = {
    "greenhouse": "https://boards-api.greenhouse.io/v1/boards/{token}/jobs",
    "lever": "https://api.lever.co/v0/postings/{token}?mode=json",
    "ashby": "https://api.ashbyhq.com/posting-api/job-board/{token}",
}

# Politeness: these are free public endpoints, so keep concurrent probes modest.
_PROBE_CONCURRENCY = 8


def load_cached_tokens() -> Dict[str, List[str]]:
    """Read the discovered-token cache; a missing or corrupt file is simply empty."""
    if not CACHE_PATH.exists():
        return {}
    try:
        data = json.loads(CACHE_PATH.read_text(encoding="utf-8"))
        return {k: list(v) for k, v in data.items() if isinstance(v, list)}
    except Exception as e:
        logger.warning(f"Ignoring unreadable board token cache {CACHE_PATH}: {e}")
        return {}


def save_cached_tokens(tokens: Dict[str, List[str]]) -> None:
    CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
    CACHE_PATH.write_text(json.dumps(tokens, indent=2, sort_keys=True), encoding="utf-8")


def merge_board_tokens(provider: str, configured: Optional[Iterable[str]]) -> Optional[List[str]]:
    """Combine YAML-configured slugs with auto-discovered ones, preserving order.

    Returns None when there is nothing to supply, which makes the connector fall back to the
    defaults in its own __init__.
    """
    combined = list(configured or []) + load_cached_tokens().get(provider, [])
    deduped = list(dict.fromkeys(t for t in combined if t))
    return deduped or None


def slug_candidates(company_name: str) -> List[str]:
    """Derive plausible board slugs from a company name ('Acme AI, Inc.' -> acmeai, acme-ai).

    Deliberately does NOT try the first word alone for multi-word names: "General Intuition"
    would probe "general", which resolves to a large unrelated company's board rather than the
    startup we meant. A wrong-company board is worse than a missed one.

    ponytail: single-word company names ("Guild", "Stage") can still collide with an unrelated
    firm's board. The stage/domain knockouts drop those downstream at the cost of one LLM call;
    verify the slug against the company's own website if that waste ever shows up in the logs.
    """
    cleaned = re.sub(r"[^a-z0-9\s-]", "", company_name.lower()).strip()
    cleaned = re.sub(r"\b(inc|llc|ltd|corp|co|labs?|technologies|technology)\b", "", cleaned).strip()
    if not cleaned:
        return []
    words = cleaned.split()
    return list(dict.fromkeys(filter(None, ["".join(words), "-".join(words)])))


async def _probe(client: httpx.AsyncClient, provider: str, token: str) -> bool:
    """True when the board exists AND currently lists at least one job.

    Requiring a non-empty board keeps the cache from filling with hundreds of live-but-empty
    slugs that would cost sweep time on every run for nothing.
    """
    try:
        resp = await client.get(PROBE_URLS[provider].format(token=token))
        if resp.status_code != 200:
            return False
        data = resp.json()
    except Exception:
        return False

    if provider == "greenhouse":
        return bool(data.get("jobs"))
    if provider == "lever":
        return isinstance(data, list) and len(data) > 0
    return bool(data.get("jobs"))  # ashby


async def fetch_yc_company_names(batch_count: int = 6) -> List[str]:
    """Pull company names from the same free YC mirror the yc_directory connector uses."""
    names: List[str] = []
    async with httpx.AsyncClient(timeout=20.0, follow_redirects=True) as client:
        try:
            targets = await fetch_recent_batches(client, count=batch_count)
        except Exception as e:
            logger.warning(f"Could not list YC batches for token expansion: {e}")
            return []

        for batch_slug, api_url in targets:
            try:
                resp = await client.get(api_url)
                if resp.status_code != 200:
                    continue
                names.extend(c["name"] for c in resp.json() if c.get("name"))
            except Exception as e:
                logger.debug(f"YC name fetch failed for {batch_slug}: {e}")
    return list(dict.fromkeys(names))


async def expand_board_tokens(company_names: Optional[List[str]] = None) -> Dict[str, List[str]]:
    """Probe candidate slugs against all three boards and merge live hits into the cache.

    Returns the newly-found tokens per provider (not the full cache).
    """
    names = company_names if company_names is not None else await fetch_yc_company_names()
    if not names:
        logger.info("Board token expansion: no company names to probe.")
        return {}

    cache = load_cached_tokens()
    known = {p: set(cache.get(p, [])) for p in PROBE_URLS}
    semaphore = asyncio.Semaphore(_PROBE_CONCURRENCY)
    found: Dict[str, List[str]] = {p: [] for p in PROBE_URLS}

    async with httpx.AsyncClient(timeout=15.0, follow_redirects=True) as client:

        async def check(provider: str, token: str) -> None:
            async with semaphore:
                if await _probe(client, provider, token):
                    found[provider].append(token)
                    logger.info(f"Discovered live {provider} board: {token}")

        # Distinct (provider, token) pairs only - different companies routinely yield the
        # same candidate slug, and probing it repeatedly is wasted requests.
        pairs = {
            (provider, token)
            for name in names
            for token in slug_candidates(name)
            for provider in PROBE_URLS
            if token not in known[provider]
        }
        tasks = [check(provider, token) for provider, token in sorted(pairs)]
        logger.info(f"Board token expansion: probing {len(tasks)} candidates from {len(names)} companies.")
        await asyncio.gather(*tasks, return_exceptions=True)

    for provider, tokens in found.items():
        if tokens:
            cache[provider] = list(dict.fromkeys(cache.get(provider, []) + sorted(tokens)))
    if any(found.values()):
        save_cached_tokens(cache)

    logger.info(
        "Board token expansion complete: "
        + ", ".join(f"{p}+{len(t)}" for p, t in found.items())
    )
    return found


if __name__ == "__main__":
    assert slug_candidates("Acme AI, Inc.") == ["acmeai", "acme-ai"]
    assert slug_candidates("Modal") == ["modal"]
    assert slug_candidates("!!!") == []
    # A multi-word name must never collapse to its first word alone: "general" resolves to a
    # large unrelated company's board rather than the YC startup we meant.
    assert "general" not in slug_candidates("General Intuition")
    print("board_tokens self-check OK")
