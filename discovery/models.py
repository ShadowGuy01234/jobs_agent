"""Data models for discovery engine."""

from enum import Enum
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field


class DiscoverySource(str, Enum):
    ASHBY = "ashby"
    GREENHOUSE = "greenhouse"
    LEVER = "lever"
    YC_DIRECTORY = "yc_directory"
    PRODUCT_HUNT = "product_hunt"
    HACKER_NEWS = "hacker_news"
    INDIAN_STARTUPS = "indian_startups"
    SEC_EDGAR = "sec_edgar"
    VC_STEALTH = "vc_stealth"
    TAVILY_STEALTH = "tavily_stealth"
    WATCHLIST = "watchlist"
    MANUAL = "manual"


class OpportunityType(str, Enum):
    JOB_POSTING = "job_posting"
    FOUNDER_REACHOUT = "founder_reachout"
    STEALTH_REACHOUT = "stealth_reachout"


class CompanyInfo(BaseModel):
    name: str
    domain: Optional[str] = None
    website: Optional[str] = None
    stage: str = "unknown"  # pre_seed, seed, series_a, series_b, series_c, unknown
    description: Optional[str] = None
    tech_stack: List[str] = Field(default_factory=list)
    funding_info: Optional[str] = None
    country: Optional[str] = None
    is_stealth: bool = False
    founders: List[str] = Field(default_factory=list)


class RawOpportunity(BaseModel):
    source: DiscoverySource
    type: OpportunityType
    title: str
    url: str
    company: CompanyInfo
    external_id: Optional[str] = None
    location: Optional[str] = "Remote"
    is_remote: bool = True
    raw_content: Optional[str] = None
    metadata: Dict[str, Any] = Field(default_factory=dict)
