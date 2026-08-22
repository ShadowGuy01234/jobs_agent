"""Lightweight, zero-cost email deliverability verification: MX lookup + SMTP RCPT TO probe.

No third-party verification API required. Two important caveats:

1. Many cloud/VPS providers and residential ISPs block outbound port 25 entirely. When that
   happens the probe cannot complete and we return "unknown" - never "invalid" - so a blocked
   probe doesn't silently discard a real contact.
2. Some mail servers are configured as a "catch-all" (they accept RCPT TO for any address at the
   domain to avoid leaking which addresses are real). A "verified" result is trustworthy; an
   "unknown" result is not proof either way.

Both functions are synchronous (blocking) by design - callers running inside an async event loop
should offload them via `asyncio.to_thread(...)`.
"""

import logging
import re
import smtplib
import socket
from typing import Literal, Optional

import dns.resolver

logger = logging.getLogger(__name__)

VerifyResult = Literal["verified", "invalid", "unknown"]

_EMAIL_RE = re.compile(r"^[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}$")


def get_mx_host(domain: str, timeout: float = 5.0) -> Optional[str]:
    """Return the highest-priority MX host for a domain, or None if lookup fails."""
    if not domain:
        return None
    try:
        answers = dns.resolver.resolve(domain, "MX", lifetime=timeout)
        best = min(answers, key=lambda r: r.preference)
        return str(best.exchange).rstrip(".")
    except Exception as e:
        logger.debug(f"MX lookup failed for {domain}: {e}")
        return None


def verify_email_smtp(
    email: str,
    sender_probe: str = "verify@example.com",
    timeout: float = 6.0,
) -> VerifyResult:
    """Best-effort deliverability check via MX lookup + SMTP RCPT TO (no message is sent).

    Returns:
        "verified": the mailbox's own server explicitly accepted the recipient (250/251).
        "invalid":  the mailbox's own server explicitly rejected it (550/551/553/554).
        "unknown":  syntax is fine but nothing could be confirmed (port 25 blocked, timeout,
                    greylisting, catch-all domain, or any other inconclusive response).
    """
    if not email or "@" not in email or not _EMAIL_RE.match(email):
        return "invalid"

    domain = email.rsplit("@", 1)[1]
    mx_host = get_mx_host(domain, timeout=timeout)
    if not mx_host:
        return "unknown"

    try:
        with smtplib.SMTP(mx_host, 25, timeout=timeout) as server:
            server.ehlo_or_helo_if_needed()
            server.mail(sender_probe)
            code, _msg = server.rcpt(email)
            if code in (250, 251):
                return "verified"
            if code in (550, 551, 553, 554):
                return "invalid"
            return "unknown"
    except (socket.timeout, socket.gaierror, ConnectionRefusedError, smtplib.SMTPException, OSError) as e:
        logger.debug(f"SMTP probe inconclusive for {email} via {mx_host}: {e}")
        return "unknown"
