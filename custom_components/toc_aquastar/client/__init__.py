"""Aquastar client for Town of Cary water usage data."""

from .client import AquastarClient, make_ssl_context
from .exceptions import (
    ApiError,
    AquastarError,
    AuthenticationError,
    CannotConnectError,
    DataParsingError,
    InvalidSecTokenError,
    SessionExpiredError,
)
from .models import WaterUsageReading

__all__ = [
    "ApiError",
    "AquastarClient",
    "AquastarError",
    "AuthenticationError",
    "CannotConnectError",
    "DataParsingError",
    "InvalidSecTokenError",
    "SessionExpiredError",
    "WaterUsageReading",
    "make_ssl_context",
]
