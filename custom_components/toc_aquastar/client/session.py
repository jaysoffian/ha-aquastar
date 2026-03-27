"""Session management for the Aquastar portal."""

from __future__ import annotations

import base64
import json
import logging
import re
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

from .const import (
    BASE_URL,
    DEFAULT_HEADERS,
    ENDPOINT_RUN,
    JWT_REFRESH_BUFFER_HOURS,
    PJ_LIB,
    RE_DATE_FIELD_PREFIX,
    RE_MENU_ITEM,
    RE_PJ_GROUP_ID,
    RE_PJ_PAGE_ID,
    RE_PJ_SESSION_ID,
    RE_SEARCH_PJMR,
    RE_XLS_PJMR,
)
from .exceptions import (
    ApiError,
    CannotConnectError,
    DataParsingError,
    InvalidSecTokenError,
    SessionExpiredError,
)
from .models import HourlyPageState, PageState, SessionInfo

if TYPE_CHECKING:
    import aiohttp

_LOGGER = logging.getLogger(__name__)


class SessionManager:
    """Manages Aquastar portal sessions.

    Handles session establishment via sectoken URL visit,
    extraction of dynamic form fields from page HTML,
    JWT expiration tracking, and automatic session refresh.
    """

    def __init__(
        self,
        websession: aiohttp.ClientSession,
        *,
        sectoken: str,
    ) -> None:
        self._websession = websession
        self._sectoken = sectoken
        self._session_info: SessionInfo | None = None

    @property
    def is_session_valid(self) -> bool:
        if self._session_info is None:
            return False
        if self._session_info.jwt_expires_at is None:
            return True
        buffer = timedelta(hours=JWT_REFRESH_BUFFER_HOURS)
        return datetime.now(UTC) + buffer < self._session_info.jwt_expires_at

    async def async_ensure_valid_session(self) -> SessionInfo:
        """Return a valid session, establishing or refreshing as needed."""
        if not self.is_session_valid:
            await self.async_establish_session()
        assert self._session_info is not None
        return self._session_info

    async def async_establish_session(self) -> SessionInfo:
        """Establish a new session by visiting the sectoken URL and navigating."""
        _LOGGER.debug("Establishing new Aquastar session")

        # Step 1: Visit sectoken URL to get dashboard + cookies
        dashboard_html, cookies = await self._async_get_dashboard()

        # Extract cookies
        jsessionid = cookies.get("JSESSIONID")
        jwt_token = cookies.get("wow.user")
        if not jsessionid or not jwt_token:
            msg = "Missing session cookies after sectoken visit"
            raise InvalidSecTokenError(msg)

        # Parse dashboard
        dashboard_state, hourly_pjmr = self._parse_dashboard(dashboard_html)
        _LOGGER.debug(
            "Dashboard parsed: PJ_SESSION_ID=%s, hourly PJMR=%s",
            dashboard_state.pj_session_id,
            hourly_pjmr,
        )

        # Step 2: Navigate to hourly view
        hourly_html = await self._async_navigate_to_hourly(
            dashboard_state, hourly_pjmr, jsessionid, jwt_token
        )
        hourly_page = self._parse_hourly_page(hourly_html)
        _LOGGER.debug(
            "Hourly page parsed: date_field_prefix=%s, xls_pjmr=%s",
            hourly_page.date_field_prefix,
            hourly_page.xls_pjmr,
        )

        # Build session info
        jwt_expires_at = self._decode_jwt_expiry(jwt_token)
        self._session_info = SessionInfo(
            jsessionid=jsessionid,
            jwt_token=jwt_token,
            jwt_expires_at=jwt_expires_at,
            hourly_page=hourly_page,
        )

        _LOGGER.debug(
            "Session established, JWT expires at %s",
            jwt_expires_at,
        )
        return self._session_info

    async def _async_get_dashboard(self) -> tuple[str, dict[str, str]]:
        """GET the sectoken URL, return (html, cookies_dict)."""
        url = f"{BASE_URL}{ENDPOINT_RUN}?id=0&sectoken={self._sectoken}"
        try:
            async with self._websession.get(url, headers=DEFAULT_HEADERS) as resp:
                if resp.status != 200:
                    msg = f"Sectoken URL returned status {resp.status}"
                    raise InvalidSecTokenError(msg)
                html = await resp.text(encoding="iso-8859-1")
                cookies: dict[str, str] = {}
                for cookie in resp.cookies.values():
                    cookies[cookie.key] = cookie.value
                return html, cookies
        except (TimeoutError, OSError) as err:
            msg = "Failed to connect to Aquastar portal"
            raise CannotConnectError(msg) from err

    async def _async_navigate_to_hourly(
        self,
        dashboard_state: PageState,
        hourly_pjmr: str,
        jsessionid: str,
        jwt_token: str,
    ) -> str:
        """POST to navigate from dashboard to hourly view page."""
        url = f"{BASE_URL}{ENDPOINT_RUN}?id=0"
        form_data = {
            "PJ_SESSION_ID": dashboard_state.pj_session_id,
            "PJ_REQUEST_ID": "0",
            "PJ_GROUP_ID": dashboard_state.pj_group_id,
            "PJ_PAGE_ID": dashboard_state.pj_page_id,
            "PJMR": hourly_pjmr,
            "URLShortcutFilter": "",
            "_pj_lib": PJ_LIB,
            "ACTION_REQUESTED": "",
            "PJMRRC": "",
            "PJMRP1": "",
            "deappsid": "0",
            "mdalias": "DEFAULT",
            "opid": "",
            "_pjWinType": "0",
        }
        headers = {
            **DEFAULT_HEADERS,
            "Content-Type": "application/x-www-form-urlencoded",
            "Referer": f"{BASE_URL}{ENDPOINT_RUN}?id=0",
            "Cookie": f"JSESSIONID={jsessionid}; wow.user={jwt_token}",
        }
        try:
            async with self._websession.post(
                url, data=form_data, headers=headers
            ) as resp:
                if resp.status == 401:
                    msg = "Session expired during navigation to hourly page"
                    raise SessionExpiredError(msg)
                if resp.status != 200:
                    msg = f"Navigation to hourly page returned status {resp.status}"
                    raise ApiError(msg, status_code=resp.status, response_text="")
                return await resp.text(encoding="iso-8859-1")
        except (TimeoutError, OSError) as err:
            msg = "Failed to connect to Aquastar portal"
            raise CannotConnectError(msg) from err

    def _parse_dashboard(self, html: str) -> tuple[PageState, str]:
        """Extract page state and hourly menu PJMR code from dashboard HTML."""
        page_state = self.extract_page_state(html)

        match = re.search(RE_MENU_ITEM, html)
        if not match:
            msg = "Could not find 'Water Usage by Hour' menu item in dashboard"
            raise DataParsingError(msg)

        return page_state, match.group(1)

    def _parse_hourly_page(self, html: str) -> HourlyPageState:
        """Extract full hourly page state including date fields and XLS PJMR."""
        page_state = self.extract_page_state(html)

        match = re.search(RE_DATE_FIELD_PREFIX, html)
        if not match:
            msg = "Could not find date field prefix in hourly page"
            raise DataParsingError(msg)
        date_field_prefix = match.group(1)

        match = re.search(RE_SEARCH_PJMR, html)
        if not match:
            msg = "Could not find Search button in hourly page"
            raise DataParsingError(msg)
        search_pjmr = match.group(1)

        match = re.search(RE_XLS_PJMR, html)
        if not match:
            msg = "Could not find XLS download link in hourly page"
            raise DataParsingError(msg)
        xls_pjmr = match.group(1)

        return HourlyPageState(
            pj_session_id=page_state.pj_session_id,
            pj_group_id=page_state.pj_group_id,
            pj_page_id=page_state.pj_page_id,
            date_field_prefix=date_field_prefix,
            search_pjmr=search_pjmr,
            xls_pjmr=xls_pjmr,
        )

    def extract_page_state(self, html: str) -> PageState:
        """Extract PJ_SESSION_ID, PJ_GROUP_ID, PJ_PAGE_ID from hidden fields."""
        session_match = re.search(RE_PJ_SESSION_ID, html)
        group_match = re.search(RE_PJ_GROUP_ID, html)
        page_match = re.search(RE_PJ_PAGE_ID, html)

        if not session_match or not group_match or not page_match:
            msg = "Could not extract page state from HTML"
            raise DataParsingError(msg)

        return PageState(
            pj_session_id=session_match.group(1),
            pj_group_id=group_match.group(1),
            pj_page_id=page_match.group(1),
        )

    def _decode_jwt_expiry(self, jwt_token: str) -> datetime | None:
        """Extract exp claim from wow.user JWT (no signature verification)."""
        try:
            parts = jwt_token.split(".")
            if len(parts) < 2:
                return None
            # JWT payload is base64url encoded
            payload_b64 = parts[1]
            # Add padding if needed
            padding = 4 - len(payload_b64) % 4
            if padding != 4:
                payload_b64 += "=" * padding
            payload_bytes = base64.urlsafe_b64decode(payload_b64)
            payload = json.loads(payload_bytes)
            exp = payload.get("exp")
            if exp is None:
                return None
            return datetime.fromtimestamp(int(exp), tz=UTC)
        except (ValueError, KeyError, json.JSONDecodeError):
            _LOGGER.debug("Failed to decode JWT expiry", exc_info=True)
            return None
