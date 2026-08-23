"""Pydantic schemas for candidate profile, targeting criteria, and resume data."""

from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field


class WritingStyle(BaseModel):
    tone: str = "Concise, technical, direct, humble"
    max_words: int = 120
    anti_patterns: List[str] = Field(default_factory=list)
    # Scheduling ask — all defaulted so an existing user_profile.yaml keeps loading unchanged.
    timezone: str = "Asia/Kolkata"
    timezone_label: str = "IST"
    meeting_window: str = "7-9pm"
    meeting_minutes: int = 15


class CandidateInfo(BaseModel):
    full_name: str
    email: str
    phone: Optional[str] = None
    linkedin: Optional[str] = None
    github: Optional[str] = None
    portfolio_url: Optional[str] = None
    resume_url: Optional[str] = None
    headline: str
    years_of_experience: int = 2
    core_skills: List[str] = Field(default_factory=list)
    key_achievements: List[str] = Field(default_factory=list)
    writing_style: WritingStyle = Field(default_factory=WritingStyle)


class LocationPreferences(BaseModel):
    remote_only: bool = True
    prioritized_regions: List[str] = Field(
        default_factory=lambda: ["India", "Remote Worldwide", "United States", "Europe"]
    )


class TargetingCriteria(BaseModel):
    target_stages: List[str] = Field(
        default_factory=lambda: ["pre_seed", "seed", "series_a", "series_b", "series_c"]
    )
    target_domains: List[str] = Field(default_factory=list)
    target_roles: List[str] = Field(default_factory=list)
    location: LocationPreferences = Field(default_factory=LocationPreferences)
    excluded_sectors: List[str] = Field(default_factory=list)
    min_fit_score: int = 75
    max_alerts_per_day: int = 10


class DiscoveryTargets(BaseModel):
    """Per-connector target lists, so retargeting never needs a code edit.

    Every field defaults to empty; a connector receiving an empty list falls back to the
    defaults baked into its own __init__, so an older user_profile.yaml still works.
    """

    greenhouse_boards: List[str] = Field(default_factory=list)
    lever_boards: List[str] = Field(default_factory=list)
    ashby_boards: List[str] = Field(default_factory=list)
    yc_batches: List[str] = Field(default_factory=list)
    hn_queries: List[str] = Field(default_factory=list)
    india_rss: List[str] = Field(default_factory=list)
    vc_rss: List[str] = Field(default_factory=list)
    watchlist: List[Dict[str, Any]] = Field(default_factory=list)


class UserProfile(BaseModel):
    candidate: CandidateInfo
    targeting: TargetingCriteria
    discovery: DiscoveryTargets = Field(default_factory=DiscoveryTargets)
    resume_text: Optional[str] = None
