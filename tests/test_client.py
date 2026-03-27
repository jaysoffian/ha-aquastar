# pyright: reportPrivateUsage=false
"""Tests for Aquastar client XLS parsing."""

from __future__ import annotations

from datetime import date, datetime
from pathlib import Path
from unittest.mock import MagicMock
from zoneinfo import ZoneInfo

import pytest

from custom_components.toc_aquastar.client.client import AquastarClient
from custom_components.toc_aquastar.client.exceptions import DataParsingError
from custom_components.toc_aquastar.client.models import HourlyPageState

FIXTURES = Path(__file__).parent / "fixtures"
_TZ = ZoneInfo("America/New_York")


def _make_client() -> AquastarClient:
    websession = MagicMock()
    return AquastarClient(websession, sectoken="AABBCC")


class TestParseXls:
    def test_parse_xls(self) -> None:
        data = (FIXTURES / "usage.xls").read_bytes()
        client = _make_client()
        readings = client._parse_xls(data)
        assert len(readings) == 6
        # Should be sorted ascending
        for i in range(1, len(readings)):
            assert readings[i].timestamp >= readings[i - 1].timestamp
        # First reading (earliest)
        assert readings[0].timestamp == datetime(2026, 1, 3, 10, 0, tzinfo=_TZ)
        assert readings[0].usage_gallons == 15
        assert readings[0].meter_number == "00012345"
        # Last reading (latest)
        assert readings[-1].timestamp == datetime(2026, 1, 3, 15, 0, tzinfo=_TZ)
        assert readings[-1].usage_gallons == 10
        # Summary row should be excluded
        for r in readings:
            assert r.meter_number

    def test_invalid_xls_data(self) -> None:
        client = _make_client()
        with pytest.raises(DataParsingError, match="Failed to parse"):
            client._parse_xls(b"not an xls file at all")


class TestParseXlsDatetime:
    def test_standard_format(self) -> None:
        client = _make_client()
        result = client._parse_xls_datetime("03/26/26  3:00 PM")
        assert result is not None
        assert result == datetime(2026, 3, 26, 15, 0, tzinfo=_TZ)

    def test_single_space(self) -> None:
        client = _make_client()
        result = client._parse_xls_datetime("03/26/26 3:00 PM")
        assert result is not None
        assert result == datetime(2026, 3, 26, 15, 0, tzinfo=_TZ)

    def test_midnight(self) -> None:
        client = _make_client()
        result = client._parse_xls_datetime("03/26/26 12:00 AM")
        assert result is not None
        assert result == datetime(2026, 3, 26, 0, 0, tzinfo=_TZ)

    def test_noon(self) -> None:
        client = _make_client()
        result = client._parse_xls_datetime("03/26/26 12:00 PM")
        assert result is not None
        assert result == datetime(2026, 3, 26, 12, 0, tzinfo=_TZ)

    def test_invalid(self) -> None:
        client = _make_client()
        assert client._parse_xls_datetime("not a date") is None

    def test_empty(self) -> None:
        client = _make_client()
        assert client._parse_xls_datetime("") is None


class TestBuildFormData:
    def test_form_fields(self) -> None:
        client = _make_client()
        page = HourlyPageState(
            pj_session_id="test-uuid",
            pj_group_id="1",
            pj_page_id="0",
            date_field_prefix="264819104",
            search_pjmr="PJMR14",
            xls_pjmr="PJMR17",
        )
        body = client._build_form_data(
            page,
            date(2026, 3, 24),
            date(2026, 3, 27),
            page.xls_pjmr,
        )
        assert "PJ_SESSION_ID=test-uuid" in body
        assert "PJMR=PJMR17" in body
        # ¤ must be encoded as %A4 (iso-8859-1), not %C2%A4 (UTF-8)
        assert "%A4264819104_4=03%2F24%2F2026" in body
        assert "%A4264819104_5=03%2F27%2F2026" in body
        # PJ_Ext_Fld appears twice (duplicate keys)
        assert body.count("PJ_Ext_Fld=") == 2
