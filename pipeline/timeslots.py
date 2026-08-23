"""Date-aware scheduling helpers for outreach drafting.

The drafting prompt used to hardcode "Would Tuesday or Thursday afternoon work?", so every
email proposed the same two days regardless of when it was actually sent — including emails
that landed on a Thursday evening proposing that same Thursday. These helpers give the prompt
real, always-future weekdays instead.

Stdlib only (datetime + zoneinfo); no new dependency.
"""

from datetime import datetime, timedelta
from typing import List, Optional
from zoneinfo import ZoneInfo

DEFAULT_TZ = "Asia/Kolkata"


def _now_in(tz: str) -> datetime:
    try:
        return datetime.now(ZoneInfo(tz))
    except Exception:
        # An unknown/missing tzdata name must not take the whole draft down.
        return datetime.now(ZoneInfo(DEFAULT_TZ))


def next_business_days(
    now: Optional[datetime] = None, tz: str = DEFAULT_TZ, count: int = 2
) -> List[str]:
    """Return the next `count` weekday names, starting at least one full day out.

    Always future, never a weekend, and never the current day — proposing "Thursday" in an
    email that arrives Thursday afternoon is the exact failure this replaces.
    """
    current = now or _now_in(tz)
    days: List[str] = []
    offset = 1
    while len(days) < count:
        candidate = current + timedelta(days=offset)
        if candidate.weekday() < 5:  # Mon-Fri
            days.append(candidate.strftime("%A"))
        offset += 1
    return days


def today_context(now: Optional[datetime] = None, tz: str = DEFAULT_TZ) -> str:
    """One-line 'today' description for prompt injection."""
    current = now or _now_in(tz)
    return current.strftime("%A, %d %B %Y")


def is_poor_send_window(now: Optional[datetime] = None, tz: str = DEFAULT_TZ) -> Optional[str]:
    """Return a short reason when this is a weak moment to send, else None.

    Per data/template_outrach.md:188 — Tue-Thu is prime, Monday inboxes are chaos and Friday
    afternoons are dead. Advisory only; nothing in the send path blocks on this.
    """
    current = now or _now_in(tz)
    weekday = current.weekday()
    if weekday >= 5:
        return "weekend — cold email open rates drop sharply"
    if weekday == 0:
        return "Monday — inboxes are busiest, Tue–Thu lands better"
    if weekday == 4 and current.hour >= 12:
        return "Friday afternoon — replies commonly stall over the weekend"
    return None


if __name__ == "__main__":
    tz = ZoneInfo(DEFAULT_TZ)

    # Never returns a weekend, never the same day, always strictly future.
    for day in range(1, 29):
        ref = datetime(2026, 8, day, 15, 0, tzinfo=tz)
        got = next_business_days(ref)
        assert len(got) == 2, got
        assert all(d not in ("Saturday", "Sunday") for d in got), (ref, got)
        assert got[0] != ref.strftime("%A") or ref.weekday() >= 5, (ref, got)

    # Fri/Sat/Sun all roll forward to the start of the next week.
    assert next_business_days(datetime(2026, 8, 21, 9, 0, tzinfo=tz)) == ["Monday", "Tuesday"]
    assert next_business_days(datetime(2026, 8, 22, 9, 0, tzinfo=tz)) == ["Monday", "Tuesday"]
    assert next_business_days(datetime(2026, 8, 23, 9, 0, tzinfo=tz)) == ["Monday", "Tuesday"]
    # Mid-week advances normally, skipping the weekend where it falls.
    assert next_business_days(datetime(2026, 8, 24, 9, 0, tzinfo=tz)) == ["Tuesday", "Wednesday"]
    assert next_business_days(datetime(2026, 8, 27, 9, 0, tzinfo=tz)) == ["Friday", "Monday"]

    assert is_poor_send_window(datetime(2026, 8, 22, 9, 0, tzinfo=tz))  # Saturday
    assert is_poor_send_window(datetime(2026, 8, 24, 9, 0, tzinfo=tz))  # Monday
    assert is_poor_send_window(datetime(2026, 8, 28, 15, 0, tzinfo=tz))  # Fri PM
    assert is_poor_send_window(datetime(2026, 8, 26, 10, 0, tzinfo=tz)) is None  # Wed

    assert today_context(datetime(2026, 8, 24, 9, 0, tzinfo=tz)) == "Monday, 24 August 2026"
    print("timeslots self-check OK")
