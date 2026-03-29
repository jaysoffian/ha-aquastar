# pyright: reportPrivateUsage=false
"""Tests for Aquastar client."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from custom_components.toc_aquastar.client import (
    WaterUsageReading,
    _encode_form,
    _FormData,
)

FIXTURES = Path(__file__).parent / "fixtures"
_TZ = ZoneInfo("America/New_York")


class TestParseUsageTable:
    def test_parse_results(self) -> None:
        html = (FIXTURES / "results.html").read_text()
        readings = WaterUsageReading.parse_table(html)
        assert len(readings) == 6
        # Should be sorted ascending
        for i in range(1, len(readings)):
            assert readings[i].timestamp >= readings[i - 1].timestamp
        # First reading (earliest after sort)
        assert readings[0].timestamp == datetime(2026, 1, 3, 10, 0, tzinfo=_TZ)
        assert readings[0].usage_gallons == 10
        assert readings[0].meter_number == "00012345"
        # Last reading (latest after sort)
        assert readings[-1].timestamp == datetime(2026, 1, 3, 15, 0, tzinfo=_TZ)
        assert readings[-1].usage_gallons == 10
        # Summary row should be excluded
        for r in readings:
            assert r.meter_number

    def test_no_results(self) -> None:
        readings = WaterUsageReading.parse_table("<html><body></body></html>")
        assert readings == []


class TestParseForm:
    def test_parse_dashboard(self) -> None:
        html = (FIXTURES / "dashboard.html").read_text(encoding="iso-8859-1")
        form = _FormData.parse(html)
        assert form.hidden["PJ_SESSION_ID"] == "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"
        assert form.hidden["PJ_GROUP_ID"] == "0"
        assert form.hidden["PJ_PAGE_ID"] == "1"
        assert "Water Usage by Hour" in form.menu

    def test_parse_hourly_page(self) -> None:
        html = (FIXTURES / "hourly.html").read_text(encoding="iso-8859-1")
        form = _FormData.parse(html)
        assert form.hidden["PJ_SESSION_ID"] == "11111111-2222-3333-4444-555555555555"
        assert form.hidden["PJ_GROUP_ID"] == "1"
        assert form.hidden["PJ_PAGE_ID"] == "0"
        assert len(form.date_fields) >= 2
        assert form.search_pjmr == "PJMR14"

    def test_missing_page_state(self) -> None:
        form = _FormData.parse("<html></html>")
        assert "PJ_SESSION_ID" not in form.hidden


class TestEncodeForm:
    def test_iso8859_encoding(self) -> None:
        """The ¤ character must be encoded as %A4 (iso-8859-1), not %C2%A4."""
        fields = [
            ("PJ_SESSION_ID", "test-uuid"),
            ("\u00a4264819104_4", "03/24/2026"),
            ("PJ_Ext_Fld", "\u00a4264819104_4"),
            ("\u00a4264819104_5", "03/27/2026"),
            ("PJ_Ext_Fld", "\u00a4264819104_5"),
        ]
        body = _encode_form(fields).decode("ascii")
        assert "PJ_SESSION_ID=test-uuid" in body
        # ¤ must be encoded as %A4 (iso-8859-1), not %C2%A4 (UTF-8)
        assert "%A4264819104_4=03%2F24%2F2026" in body
        assert "%A4264819104_5=03%2F27%2F2026" in body
        # PJ_Ext_Fld appears twice (duplicate keys)
        assert body.count("PJ_Ext_Fld=") == 2
