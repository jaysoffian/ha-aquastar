"""Aquastar client for fetching water usage data."""

from __future__ import annotations

import logging
import re
import ssl
from datetime import datetime
from typing import TYPE_CHECKING
from urllib.parse import quote
from zoneinfo import ZoneInfo

import aiohttp
import xlrd
from xlrd.biffh import XLRDError

from .const import BASE_URL, DEFAULT_HEADERS, ENDPOINT_RUN, PJ_LIB, TIMEZONE
from .exceptions import (
    ApiError,
    CannotConnectError,
    DataParsingError,
    SessionExpiredError,
)
from .models import HourlyPageState, WaterUsageReading
from .session import SessionManager

if TYPE_CHECKING:
    from datetime import date

_LOGGER = logging.getLogger(__name__)


def _urlencode_iso8859(fields: list[tuple[str, str]]) -> str:
    """URL-encode form fields using iso-8859-1 (not UTF-8).

    The Aquastar server expects the ¤ character (U+00A4) to be encoded
    as %A4 (iso-8859-1), not %C2%A4 (UTF-8).
    """
    parts = []
    for key, value in fields:
        encoded_key = quote(key, safe="", encoding="iso-8859-1")
        encoded_value = quote(value, safe="", encoding="iso-8859-1")
        parts.append(f"{encoded_key}={encoded_value}")
    return "&".join(parts)


_TZ = ZoneInfo(TIMEZONE)

# Datetime format in XLS: "MM/DD/YY  H:MM AM" (variable whitespace)
_XLS_DATE_RE = re.compile(r"(\d{2}/\d{2}/\d{2})\s+(\d{1,2}:\d{2}\s[AP]M)")


# DigiCert EV RSA CA G2 — the correct intermediate for aquastar.townofcary.org.
# The server sends the wrong intermediate (DigiCert SHA2 Extended Validation
# Server CA), so we bundle the correct one. Valid until 2030-07-02.
_DIGICERT_EV_RSA_CA_G2_PEM = """\
-----BEGIN CERTIFICATE-----
MIIFPDCCBCSgAwIBAgIQAWePH++IIlXYsKcOa3uyIDANBgkqhkiG9w0BAQsFADBh
MQswCQYDVQQGEwJVUzEVMBMGA1UEChMMRGlnaUNlcnQgSW5jMRkwFwYDVQQLExB3
d3cuZGlnaWNlcnQuY29tMSAwHgYDVQQDExdEaWdpQ2VydCBHbG9iYWwgUm9vdCBH
MjAeFw0yMDA3MDIxMjQyNTBaFw0zMDA3MDIxMjQyNTBaMEQxCzAJBgNVBAYTAlVT
MRUwEwYDVQQKEwxEaWdpQ2VydCBJbmMxHjAcBgNVBAMTFURpZ2lDZXJ0IEVWIFJT
QSBDQSBHMjCCASIwDQYJKoZIhvcNAQEBBQADggEPADCCAQoCggEBAK0eZsx/neTr
f4MXJz0R2fJTIDfN8AwUAu7hy4gI0vp7O8LAAHx2h3bbf8wl+pGMSxaJK9ffDDCD
63FqqFBqE9eTmo3RkgQhlu55a04LsXRLcK6crkBOO0djdonybmhrfGrtBqYvbRat
xenkv0Sg4frhRl4wYh4dnW0LOVRGhbt1G5Q19zm9CqMlq7LlUdAE+6d3a5++ppfG
cnWLmbEVEcLHPAnbl+/iKauQpQlU1Mi+wEBnjE5tK8Q778naXnF+DsedQJ7NEi+b
QoonTHEz9ryeEcUHuQTv7nApa/zCqes5lXn1pMs4LZJ3SVgbkTLj+RbBov/uiwTX
tkBEWawvZH8CAwEAAaOCAgswggIHMB0GA1UdDgQWBBRqTlC/mGidW3sgddRZAXlI
ZpIyBjAfBgNVHSMEGDAWgBROIlQgGJXm427mD/r6uRLtBhePOTAOBgNVHQ8BAf8E
BAMCAYYwHQYDVR0lBBYwFAYIKwYBBQUHAwEGCCsGAQUFBwMCMBIGA1UdEwEB/wQI
MAYBAf8CAQAwNAYIKwYBBQUHAQEEKDAmMCQGCCsGAQUFBzABhhhodHRwOi8vb2Nz
cC5kaWdpY2VydC5jb20wewYDVR0fBHQwcjA3oDWgM4YxaHR0cDovL2NybDMuZGln
aWNlcnQuY29tL0RpZ2lDZXJ0R2xvYmFsUm9vdEcyLmNybDA3oDWgM4YxaHR0cDov
L2NybDQuZGlnaWNlcnQuY29tL0RpZ2lDZXJ0R2xvYmFsUm9vdEcyLmNybDCBzgYD
VR0gBIHGMIHDMIHABgRVHSAAMIG3MCgGCCsGAQUFBwIBFhxodHRwczovL3d3dy5k
aWdpY2VydC5jb20vQ1BTMIGKBggrBgEFBQcCAjB+DHxBbnkgdXNlIG9mIHRoaXMg
Q2VydGlmaWNhdGUgY29uc3RpdHV0ZXMgYWNjZXB0YW5jZSBvZiB0aGUgUmVseWlu
ZyBQYXJ0eSBBZ3JlZW1lbnQgbG9jYXRlZCBhdCBodHRwczovL3d3dy5kaWdpY2Vy
dC5jb20vcnBhLXVhMA0GCSqGSIb3DQEBCwUAA4IBAQBSMgrCdY2+O9spnYNvwHiG
+9lCJbyELR0UsoLwpzGpSdkHD7pVDDFJm3//B8Es+17T1o5Hat+HRDsvRr7d3MEy
o9iXkkxLhKEgApA2Ft2eZfPrTolc95PwSWnn3FZ8BhdGO4brTA4+zkPSKoMXi/X+
WLBNN29Z/nbCS7H/qLGt7gViEvTIdU8x+H4l/XigZMUDaVmJ+B5d7cwSK7yOoQdf
oIBGmA5Mp4LhMzo52rf//kXPfE3wYIZVHqVuxxlnTkFYmffCX9/Lon7SWaGdg6Rc
k4RHhHLWtmz2lTZ5CEo2ljDsGzCFGJP7oT4q6Q8oFC38irvdKIJ95cUxYzj4tnOI
-----END CERTIFICATE-----
"""


def make_ssl_context() -> ssl.SSLContext:
    """Build an SSL context for the Aquastar portal.

    The server sends an incorrect intermediate certificate, so standard
    verification fails. We load the correct intermediate into the context.
    """
    ctx = ssl.create_default_context()
    ctx.load_verify_locations(cadata=_DIGICERT_EV_RSA_CA_G2_PEM)
    return ctx


class AquastarClient:
    """Async client for the Town of Cary Aquastar water usage portal."""

    def __init__(
        self,
        websession: aiohttp.ClientSession,
        *,
        sectoken: str,
    ) -> None:
        self._websession = websession
        self._session_manager = SessionManager(
            websession,
            sectoken=sectoken,
        )

    async def async_get_usage(
        self,
        start_date: date,
        end_date: date,
    ) -> list[WaterUsageReading]:
        """Fetch hourly water usage readings for a date range.

        Returns readings sorted ascending by timestamp.
        """
        xls_data = await self._async_fetch_xls(start_date, end_date)
        return self._parse_xls(xls_data)

    async def _async_fetch_xls(
        self,
        start_date: date,
        end_date: date,
    ) -> bytes:
        """Fetch XLS, retrying once with a fresh session on expiry."""
        try:
            return await self._async_fetch_xls_once(start_date, end_date)
        except SessionExpiredError:
            _LOGGER.warning("Session expired mid-request, re-establishing")
            await self._session_manager.async_establish_session()
            return await self._async_fetch_xls_once(start_date, end_date)

    async def _async_fetch_xls_once(
        self,
        start_date: date,
        end_date: date,
    ) -> bytes:
        """Submit date search then download XLS data.

        Two-step process: first POST a search to set the date range on the
        server, then POST the XLS download to get data for that range.
        """
        info = await self._session_manager.async_ensure_valid_session()
        url = f"{BASE_URL}{ENDPOINT_RUN}?id=0"
        headers = {
            **DEFAULT_HEADERS,
            "Content-Type": "application/x-www-form-urlencoded",
            "Referer": f"{BASE_URL}{ENDPOINT_RUN}?id=0",
            "Cookie": f"JSESSIONID={info.jsessionid}; wow.user={info.jwt_token}",
        }

        # Step 1: Submit date search to update server-side date range
        search_body = self._build_form_data(
            info.hourly_page, start_date, end_date, info.hourly_page.search_pjmr
        )
        try:
            async with self._websession.post(
                url, data=search_body, headers=headers
            ) as resp:
                if resp.status == 401:
                    msg = "Session expired"
                    raise SessionExpiredError(msg)
                if resp.status != 200:
                    msg = f"Date search failed: {resp.status}"
                    raise ApiError(msg, status_code=resp.status, response_text="")
                # Parse updated page state (PJ_PAGE_ID changes after search)
                search_html = await resp.text(encoding="iso-8859-1")
        except (TimeoutError, OSError) as err:
            msg = "Failed to connect to Aquastar portal"
            raise CannotConnectError(msg) from err

        updated_state = self._session_manager.extract_page_state(search_html)

        # Step 2: Download XLS using updated page state
        xls_page = HourlyPageState(
            pj_session_id=updated_state.pj_session_id,
            pj_group_id=updated_state.pj_group_id,
            pj_page_id=updated_state.pj_page_id,
            date_field_prefix=info.hourly_page.date_field_prefix,
            search_pjmr=info.hourly_page.search_pjmr,
            xls_pjmr=info.hourly_page.xls_pjmr,
        )
        xls_body = self._build_form_data(
            xls_page, start_date, end_date, xls_page.xls_pjmr
        )
        try:
            async with self._websession.post(
                url, data=xls_body, headers=headers
            ) as resp:
                if resp.status == 401:
                    msg = "Session expired"
                    raise SessionExpiredError(msg)
                if resp.status != 200:
                    text = await resp.text()
                    msg = f"XLS download failed: {resp.status}"
                    raise ApiError(
                        msg,
                        status_code=resp.status,
                        response_text=text,
                    )
                data = await resp.read()
        except (TimeoutError, OSError) as err:
            msg = "Failed to connect to Aquastar portal"
            raise CannotConnectError(msg) from err

        if len(data) < 100:
            msg = "XLS response too small, likely an error page"
            raise DataParsingError(msg)

        return data

    def _build_form_data(
        self,
        page: HourlyPageState,
        start_date: date,
        end_date: date,
        pjmr: str,
    ) -> str:
        """Build URL-encoded form body for a search or XLS download POST.

        The ¤ character in field names must be encoded as iso-8859-1 (%A4),
        not UTF-8 (%C2%A4), to match the server's expectations.
        """
        start_field = f"\u00a4{page.date_field_prefix}_4"
        end_field = f"\u00a4{page.date_field_prefix}_5"
        start_str = start_date.strftime("%m/%d/%Y")
        end_str = end_date.strftime("%m/%d/%Y")

        fields = [
            ("PJ_SESSION_ID", page.pj_session_id),
            ("PJ_REQUEST_ID", "0"),
            ("PJ_GROUP_ID", page.pj_group_id),
            ("PJ_PAGE_ID", page.pj_page_id),
            ("PJMR", pjmr),
            ("URLShortcutFilter", ""),
            ("_pj_lib", PJ_LIB),
            ("ACTION_REQUESTED", ""),
            ("PJMRRC", ""),
            ("PJMRP1", ""),
            ("deappsid", "0"),
            ("mdalias", "DEFAULT"),
            ("opid", ""),
            ("_pjWinType", "0"),
            (start_field, start_str),
            ("PJ_Ext_Fld", start_field),
            (end_field, end_str),
            ("PJ_Ext_Fld", end_field),
        ]
        return _urlencode_iso8859(fields)

    def _parse_xls(self, data: bytes) -> list[WaterUsageReading]:
        """Parse XLS binary data into sorted WaterUsageReading list."""
        try:
            workbook = xlrd.open_workbook(file_contents=data)
        except XLRDError as err:
            msg = f"Failed to parse XLS data: {err}"
            raise DataParsingError(msg) from err

        sheet = workbook.sheet_by_index(0)
        readings: list[WaterUsageReading] = []

        # Row 0 is headers, data starts at row 1
        for row_idx in range(1, sheet.nrows):
            meter = sheet.cell_value(row_idx, 0)
            if not meter:
                # Summary/total row (empty meter number)
                continue

            date_str = sheet.cell_value(row_idx, 2)
            usage_str = sheet.cell_value(row_idx, 3)

            timestamp = self._parse_xls_datetime(date_str)
            if timestamp is None:
                _LOGGER.warning(
                    "Skipping row %d: unparseable date '%s'",
                    row_idx,
                    date_str,
                )
                continue

            try:
                usage = int(usage_str)
            except (ValueError, TypeError):
                _LOGGER.warning(
                    "Skipping row %d: unparseable usage '%s'",
                    row_idx,
                    usage_str,
                )
                continue

            readings.append(
                WaterUsageReading(
                    timestamp=timestamp,
                    usage_gallons=usage,
                    meter_number=str(meter),
                )
            )

        readings.sort(key=lambda r: r.timestamp)
        _LOGGER.debug("Parsed %d usage readings from XLS", len(readings))
        return readings

    def _parse_xls_datetime(self, text: str) -> datetime | None:
        """Parse XLS datetime string into tz-aware datetime.

        Handles format like '03/26/26  3:00 PM' (variable whitespace).
        """
        match = _XLS_DATE_RE.match(text.strip())
        if not match:
            return None
        date_part, time_part = match.group(1), match.group(2)
        try:
            naive = datetime.strptime(f"{date_part} {time_part}", "%m/%d/%y %I:%M %p")
        except ValueError:
            return None
        return naive.replace(tzinfo=_TZ)
