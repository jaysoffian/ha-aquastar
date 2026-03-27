"""Data models for the Aquastar client."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True)
class PageState:
    """State extracted from hidden form fields on any Aquastar page."""

    pj_session_id: str
    pj_group_id: str
    pj_page_id: str


@dataclass(frozen=True)
class HourlyPageState(PageState):
    """State from the hourly view page, includes date form fields."""

    date_field_prefix: str
    search_pjmr: str
    xls_pjmr: str


@dataclass(frozen=True)
class SessionInfo:
    """Full session state, suitable for persistence and restoration."""

    jsessionid: str
    jwt_token: str
    jwt_expires_at: datetime | None
    hourly_page: HourlyPageState


@dataclass(frozen=True)
class WaterUsageReading:
    """A single hourly water usage reading."""

    timestamp: datetime
    usage_gallons: int
    meter_number: str
