# pyright: reportPrivateUsage=false
"""Tests for Aquastar session management."""

from __future__ import annotations

import base64
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from custom_components.toc_aquastar.client.exceptions import DataParsingError
from custom_components.toc_aquastar.client.models import (
    HourlyPageState,
    SessionInfo,
)
from custom_components.toc_aquastar.client.session import SessionManager

FIXTURES = Path(__file__).parent / "fixtures"

_HOURLY_PAGE = HourlyPageState(
    pj_session_id="s",
    pj_group_id="1",
    pj_page_id="0",
    date_field_prefix="123",
    search_pjmr="PJMR14",
    xls_pjmr="PJMR17",
)


def _make_manager(
    sectoken: str = "AABBCC",
    session_info: SessionInfo | None = None,
) -> SessionManager:
    websession = MagicMock()
    mgr = SessionManager(
        websession,
        sectoken=sectoken,
    )
    if session_info is not None:
        mgr._session_info = session_info
    return mgr


def _make_session_info(
    jwt_expires_at: datetime | None = None,
) -> SessionInfo:
    return SessionInfo(
        jsessionid="abc",
        jwt_token="x.y.z",
        jwt_expires_at=jwt_expires_at,
        hourly_page=_HOURLY_PAGE,
    )


def _make_page_html(
    *,
    pj_session_id: str = "x",
    pj_group_id: str = "0",
    pj_page_id: str = "1",
) -> str:
    return (
        f'<input type="hidden" name="PJ_SESSION_ID" value="{pj_session_id}" />'
        f'<input type="hidden" name="PJ_GROUP_ID" value="{pj_group_id}" />'
        f'<input type="hidden" name="PJ_PAGE_ID" value="{pj_page_id}" />'
    )


class TestIsSessionValid:
    def test_no_session(self) -> None:
        mgr = _make_manager()
        assert not mgr.is_session_valid

    def test_no_expiry(self) -> None:
        mgr = _make_manager(session_info=_make_session_info())
        assert mgr.is_session_valid

    def test_expired(self) -> None:
        expires = datetime.now(UTC) - timedelta(hours=1)
        mgr = _make_manager(session_info=_make_session_info(jwt_expires_at=expires))
        assert not mgr.is_session_valid

    def test_valid_with_buffer(self) -> None:
        expires = datetime.now(UTC) + timedelta(days=10)
        mgr = _make_manager(session_info=_make_session_info(jwt_expires_at=expires))
        assert mgr.is_session_valid


class TestJwtDecoding:
    def test_valid_jwt(self) -> None:
        """Decode the actual wow.user JWT from the HAR capture."""
        jwt = (
            "eyJraWQiOiI0Nzg0YjkxNS0wM2Y1LTQyYWMtYTY0Ni0yYmRkYjUyMTc4OGEi"
            "LCJ0eXAiOiJKV1QiLCJhbGciOiJSUzI1NiJ9"
            "."
            "eyJhdWQiOlsicGxhbmV0aiIsInBsYW5ldGphdmFpbmMiXSwic3ViIjoiZ3Vp"
            "ZF85YWQzZTExYi1lYTAwLTRhYTUtYjBlNi1jNGI2OTEwNTA3ZjIiLCJpc3Mi"
            "OiJwbGFuZXRqIiwiZXhwIjoxNzc1ODUyOTc0LCJpYXQiOjE3NzQ2NDMzNzR9"
            "."
            "signature"
        )
        mgr = _make_manager()
        result = mgr._decode_jwt_expiry(jwt)
        assert result is not None
        assert result.year == 2026

    def test_invalid_jwt(self) -> None:
        mgr = _make_manager()
        assert mgr._decode_jwt_expiry("not-a-jwt") is None

    def test_no_exp_claim(self) -> None:
        payload = base64.urlsafe_b64encode(json.dumps({"sub": "test"}).encode()).rstrip(
            b"="
        )
        jwt = f"header.{payload.decode()}.sig"
        mgr = _make_manager()
        assert mgr._decode_jwt_expiry(jwt) is None


class TestParseDashboard:
    def test_parse_dashboard(self) -> None:
        html = (FIXTURES / "dashboard.html").read_text(encoding="iso-8859-1")
        mgr = _make_manager()
        page_state, hourly_pjmr = mgr._parse_dashboard(html)
        assert page_state.pj_session_id == "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"
        assert page_state.pj_group_id == "0"
        assert page_state.pj_page_id == "1"
        assert hourly_pjmr == "PJMR12"

    def test_missing_menu_item(self) -> None:
        html = _make_page_html()
        mgr = _make_manager()
        with pytest.raises(DataParsingError, match="Water Usage by Hour"):
            mgr._parse_dashboard(html)


class TestParseHourlyPage:
    def test_parse_hourly_page(self) -> None:
        html = (FIXTURES / "hourly.html").read_text(encoding="iso-8859-1")
        mgr = _make_manager()
        page = mgr._parse_hourly_page(html)
        assert page.pj_session_id == "11111111-2222-3333-4444-555555555555"
        assert page.pj_group_id == "1"
        assert page.pj_page_id == "0"
        assert page.date_field_prefix == "999888777"
        assert page.search_pjmr == "PJMR14"
        assert page.xls_pjmr == "PJMR17"

    def test_missing_date_field(self) -> None:
        html = _make_page_html()
        mgr = _make_manager()
        with pytest.raises(DataParsingError, match="date field"):
            mgr._parse_hourly_page(html)
