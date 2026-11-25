"""Public Telegram channel (t.me/s/<handle>) job & startup hiring feed connector."""

import asyncio
import html as html_lib
import json
import logging
import re
from typing import List, Optional, Tuple
from urllib.parse import urlparse

import httpx
from bs4 import BeautifulSoup

from db.database import get_app_setting
from discovery.base import BaseDiscoveryConnector
from discovery.models import CompanyInfo, DiscoverySource, OpportunityType, RawOpportunity
from pipeline.nodes.score_fit import check_title_relevance

logger = logging.getLogger(__name__)

DEFAULT_TELEGRAM_CHANNELS = [
    "jobs_and_internships_updates",
    "gocareers",
    "internfreak",
    "offcampusjobs4u",
    "remotejobs_ai",
]

_EMAIL_RE = re.compile(r"\b[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}\b")
_COMPANY_LINE_RE = re.compile(r"(?:company(?:\s+name)?|organization)\s*[:\-]\s*(.+)", re.IGNORECASE)
_ROLE_LINE_RE = re.compile(r"(?:role|position|profile|job\s+title)\s*[:\-]\s*(.+)", re.IGNORECASE)
_HIRING_HEADLINE_RE = re.compile(
    r"^([A-Z][A-Za-z0-9.&'\- ]{1,50}?)\s+(?:is\s+hiring|hiring\s+for|recruitment\s+\d{4}|careers)\b",
    re.IGNORECASE,
)

_NON_COMPANY_DOMAINS = (
    "t.me",
    "telegram.me",
    "linkedin.com",
    "twitter.com",
    "x.com",
    "instagram.com",
    "youtube.com",
    "youtu.be",
    "whatsapp.com",
    "chat.whatsapp.com",
    "forms.gle",
    "docs.google.com",
    "bit.ly",
    "tinyurl.com",
    "offcampusjobs4u.com",
    "internfreak.co",
    "oraclecloud.com",
    "darwinbox.in",
    "myworkdayjobs.com",
    "greenhouse.io",
    "lever.co",
    "ashbyhq.com",
    "smartrecruiters.com",
    "icims.com",
    "workable.com",
)
_FREE_EMAIL_DOMAINS = ("gmail.com", "yahoo.com", "outlook.com", "hotmail.com", "proton.me", "icloud.com")
_HIRING_SIGNALS = (
    "hiring",
    "engineer",
    "developer",
    "intern",
    "apply",
    "recruitment",
    "opening",
    "role:",
    "position:",
    "mail here",
    "send your resume",
)


def _clean_post_text(node) -> str:
    for br in node.find_all("br"):
        br.replace_with("\n")
    raw = html_lib.unescape(node.get_text(separator=" "))
    lines = [re.sub(r"\s+", " ", line).strip() for line in raw.splitlines()]
    return "\n".join(line for line in lines if line)


def _extract_company_and_role(text: str) -> Tuple[str, str]:
    company = ""
    role = ""
    for line in text.splitlines():
        if not company:
            m = _COMPANY_LINE_RE.search(line)
            if m:
                company = m.group(1).strip(" -–—|")
        if not role:
            m = _ROLE_LINE_RE.search(line)
            if m:
                role = m.group(1).strip(" -–—|")

    first_line = text.splitlines()[0].strip() if text.splitlines() else ""
    if not company and first_line:
        m = _HIRING_HEADLINE_RE.search(first_line)
        if m:
            company = m.group(1).strip(" -–—|")
        elif "—" in first_line or " - " in first_line:
            parts = re.split(r"\s+[—–\-]\s+", first_line, maxsplit=1)
            if len(parts) == 2 and len(parts[1]) <= 45:
                role = role or parts[0].strip()
                company = parts[1].strip()

    if not role:
        role = first_line[:120] or "Engineering Opportunity"
    if not company:
        company = first_line.split("|")[0].split("-")[0].strip()[:60] or "Startup Opportunity"
    return company[:80], role[:140]


def _pick_domain_and_links(text: str, hrefs: List[str]) -> Tuple[Optional[str], Optional[str], Optional[str]]:
    """Extract (company_domain, direct_email, primary_external_url) from a Telegram post."""
    emails = [e.lower() for e in _EMAIL_RE.findall(text)]
    direct_email = emails[0] if emails else None

    domain: Optional[str] = None
    if direct_email:
        edom = direct_email.split("@", 1)[1]
        if edom not in _FREE_EMAIL_DOMAINS:
            domain = edom

    primary_url: Optional[str] = None
    for href in hrefs:
        if not href.startswith("http"):
            continue
        parsed = urlparse(href)
        host = (parsed.netloc or "").lower().removeprefix("www.")
        if not host:
            continue
        if not primary_url and not any(b in host for b in ("t.me", "whatsapp.com")):
            primary_url = href
        if not domain and not any(b in host for b in _NON_COMPANY_DOMAINS):
            domain = host

    return domain, direct_email, primary_url


def parse_telegram_channel_html(channel: str, html_text: str, limit: int = 10) -> List[RawOpportunity]:
    """Parse posts from https://t.me/s/<channel> HTML into RawOpportunity objects."""
    soup = BeautifulSoup(html_text, "html.parser")
    wraps = soup.select(".tgme_widget_message_wrap")
    opportunities: List[RawOpportunity] = []

    for wrap in reversed(wraps):
        msg_el = wrap.select_one(".tgme_widget_message")
        txt_el = wrap.select_one(".tgme_widget_message_text")
        if not msg_el or not txt_el:
            continue

        data_post = (msg_el.get("data-post") or "").strip()
        text = _clean_post_text(txt_el)
        lower_text = text.lower()
        if len(text) < 40 or "pinned «" in lower_text or lower_text == "channel created":
            continue
        if not any(sig in lower_text for sig in _HIRING_SIGNALS):
            continue

        hrefs = [a.get("href", "") for a in txt_el.find_all("a", href=True)]
        domain, direct_email, primary_url = _pick_domain_and_links(text, hrefs)
        company_name, role_title = _extract_company_and_role(text)

        if check_title_relevance(role_title, OpportunityType.JOB_POSTING.value) and not direct_email:
            # Skip obvious non-engineering postings unless text itself mentions engineering
            if not any(k in lower_text for k in ("software engineer", "ai engineer", "backend", "full stack", "fullstack", "devops", "machine learning", "engineering intern")):
                continue

        post_url = f"https://t.me/{data_post}" if data_post else (primary_url or f"https://t.me/s/{channel}")
        loc = "India / Remote" if ("remote" in lower_text or "india" in lower_text or "bengaluru" in lower_text or "bangalore" in lower_text) else "India"

        company_info = CompanyInfo(
            name=company_name,
            domain=domain,
            website=f"https://{domain}" if domain else primary_url,
            stage="unknown",
            description=text[:400],
            country="India" if "india" in loc.lower() else "Remote",
            is_stealth=False,
        )

        opportunities.append(
            RawOpportunity(
                source=DiscoverySource.TELEGRAM_CHANNELS,
                type=OpportunityType.JOB_POSTING,
                title=f"{role_title} ({company_name})" if company_name.lower() not in role_title.lower() else role_title,
                url=post_url,
                company=company_info,
                external_id=data_post or None,
                location=loc,
                is_remote="remote" in lower_text,
                raw_content=text[:4000],
                metadata={
                    "channel": channel,
                    "direct_email": direct_email,
                    "primary_url": primary_url,
                },
            )
        )
        if len(opportunities) >= limit:
            break

    return opportunities


def normalize_channel_handle(raw: str) -> Optional[str]:
    """Normalize @handle or https://t.me/(s/)handle to a clean public handle.

    Returns None for private invite links (t.me/+... or joinchat/...) or invalid strings.
    """
    val = (raw or "").strip()
    if not val:
        return None
    val = re.sub(r"^https?://(?:www\.)?(?:t\.me|telegram\.me)/", "", val, flags=re.IGNORECASE)
    if val.lower().startswith("s/"):
        val = val[2:]
    val = val.strip().lstrip("@").split("?")[0].strip("/")
    if not val or val.startswith("+") or val.lower().startswith("joinchat"):
        return None
    if not re.match(r"^[A-Za-z0-9_]{3,64}$", val):
        return None
    return val


def get_active_telegram_channels(fallback_channels: Optional[List[str]] = None) -> List[str]:
    """Return active channel list (persisted bot additions/removals take precedence over YAML)."""
    try:
        raw = get_app_setting("telegram_channels")
        if raw is not None:
            loaded = json.loads(raw)
            if isinstance(loaded, list):
                cleaned = [normalize_channel_handle(c) for c in loaded]
                return [c for c in cleaned if c]
    except Exception as e:
        logger.debug(f"Could not read persisted telegram_channels: {e}")

    base = fallback_channels or DEFAULT_TELEGRAM_CHANNELS
    cleaned = [normalize_channel_handle(c) for c in base]
    return [c for c in cleaned if c]


async def validate_public_channel(channel: str) -> Tuple[bool, int, str]:
    """Verify https://t.me/s/<channel> is accessible as a public channel and count visible posts."""
    url = f"https://t.me/s/{channel}"
    try:
        async with httpx.AsyncClient(
            timeout=12.0,
            follow_redirects=True,
            headers={"User-Agent": "Mozilla/5.0 (compatible; job-outreach/1.0)"},
        ) as client:
            resp = await client.get(url)
            if resp.status_code != 200:
                return False, 0, f"HTTP {resp.status_code} from {url}"
            soup = BeautifulSoup(resp.text, "html.parser")
            has_channel_info = bool(soup.select_one(".tgme_channel_info, .tgme_page_title"))
            posts = soup.select(".tgme_widget_message_wrap")
            if not has_channel_info and not posts:
                return False, 0, "Not a public Telegram channel (no channel preview found)."
            return True, len(posts), "ok"
    except Exception as e:
        return False, 0, str(e)


class TelegramChannelsConnector(BaseDiscoveryConnector):
    """Scrape public Telegram hiring channels via https://t.me/s/<channel> (no login/API needed)."""

    source_name = DiscoverySource.TELEGRAM_CHANNELS

    def __init__(self, channels: Optional[List[str]] = None, use_persisted: bool = True):
        raw = channels or DEFAULT_TELEGRAM_CHANNELS
        cleaned = [normalize_channel_handle(c) for c in raw]
        self.channels = [c for c in cleaned if c]
        self._fallback_channels = list(self.channels)
        self.use_persisted = use_persisted

    async def _fetch_channel(self, client: httpx.AsyncClient, channel: str, limit: int) -> List[RawOpportunity]:
        url = f"https://t.me/s/{channel}"
        try:
            resp = await client.get(url)
            if resp.status_code != 200:
                logger.debug(f"Telegram channel {channel} returned HTTP {resp.status_code}")
                return []
            return parse_telegram_channel_html(channel, resp.text, limit=limit)
        except Exception as e:
            logger.warning(f"Error fetching Telegram channel {channel}: {e}")
            return []

    async def fetch_opportunities(self, limit: int = 20) -> List[RawOpportunity]:
        active_channels = (
            get_active_telegram_channels(self._fallback_channels)
            if self.use_persisted
            else self.channels
        )
        if not active_channels:
            return []
        per_channel = max(2, limit // max(1, len(active_channels)))
        opportunities: List[RawOpportunity] = []
        async with httpx.AsyncClient(
            timeout=15.0,
            follow_redirects=True,
            headers={"User-Agent": "Mozilla/5.0 (compatible; job-outreach/1.0)"},
        ) as client:
            results = await asyncio.gather(
                *(self._fetch_channel(client, ch, per_channel) for ch in active_channels),
                return_exceptions=True,
            )
            for ch, res in zip(active_channels, results):
                if isinstance(res, list):
                    opportunities.extend(res)
                elif isinstance(res, Exception):
                    logger.warning(f"Channel {ch} failed: {res}")
        return opportunities[:limit]
