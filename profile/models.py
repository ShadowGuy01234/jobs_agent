"""Pydantic schemas for candidate profile, targeting criteria, and resume data."""

from typing import List, Optional
from pydantic import BaseModel, Field


class WritingStyle(BaseModel):
    tone: str = "Concise, technical, direct, humble"
    max_words: int = 120
    anti_patterns: List[str] = Field(default_factory=list)


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


class UserProfile(BaseModel):
    candidate: CandidateInfo
    targeting: TargetingCriteria
    resume_text: Optional[str] = None
