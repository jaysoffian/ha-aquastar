"""Aquastar client for Town of Cary water usage data."""

from __future__ import annotations

import logging
import re
import ssl
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from html.parser import HTMLParser
from typing import Annotated
from urllib.parse import quote
from zoneinfo import ZoneInfo

import aiohttp

_LOGGER = logging.getLogger(__name__)

BASE_URL = "https://aquastar.townofcary.org/waterconsumption"
RUN_URL = f"{BASE_URL}/run?id=0"

TIMEZONE = "America/New_York"
_TZ = ZoneInfo(TIMEZONE)

# The page declares charset=iso-8859-1.  The ¤ (U+00A4) in field names is
# a single byte 0xA4 in Latin-1, which the browser percent-encodes as %A4.
# UTF-8 would produce %C2%A4 instead, which the server won't recognise.
FORM_CHARSET = "iso-8859-1"

FORM_CT = {"Content-Type": "application/x-www-form-urlencoded"}

# DigiCert EV RSA CA G2 — the correct intermediate for aquastar.townofcary.org.
# The server sends the wrong intermediate (DigiCert SHA2 Extended Validation
# Server CA), so we bundle the correct one.  Valid until 2030-07-02.
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


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------


class AquastarError(Exception):
    """Base exception for all Aquastar client errors."""


class AuthenticationError(AquastarError):
    """Authentication failed (invalid sectoken or expired session)."""


class CannotConnectError(AquastarError):
    """Unable to connect to the Aquastar portal."""


# ---------------------------------------------------------------------------
# Data types
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class WaterUsageReading:
    """A single hourly water usage reading."""

    timestamp: datetime
    usage_gallons: int
    meter_number: str

    def __str__(self) -> str:
        fields = [str(self.timestamp), str(self.usage_gallons), self.meter_number]
        return "\t".join(fields)


# ---------------------------------------------------------------------------
# SSL
# ---------------------------------------------------------------------------


_ssl_context: ssl.SSLContext | None = None


def _get_ssl_context() -> ssl.SSLContext:
    """Build (once) an SSL context that includes the correct intermediate cert."""
    global _ssl_context  # noqa: PLW0603
    if _ssl_context is None:
        _ssl_context = ssl.create_default_context()
        _ssl_context.load_verify_locations(cadata=_DIGICERT_EV_RSA_CA_G2_PEM)
    return _ssl_context


# ---------------------------------------------------------------------------
# HTML parsing
# ---------------------------------------------------------------------------


class _FormParser(HTMLParser):
    """Extract hidden fields, menu links, date inputs, and action PJMRs."""

    def __init__(self) -> None:
        super().__init__()
        self.hidden: dict[str, str] = {}
        self.ext_fields: list[str] = []
        self.menu: dict[str, str] = {}
        self.date_fields: list[str] = []
        self.search_pjmr: str | None = None

        self._link_pjmr: str | None = None
        self._link_text = ""
        self._in_link = False

    _PJMR_RE = re.compile(r"performMagic\('(?:URLShortcutFilter)?(PJMR\d+)'\)")

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        a = dict(attrs)
        if tag == "input":
            self._handle_input(a)
        elif tag == "a":
            onclick = a.get("onclick", "") or a.get("href", "")
            m = self._PJMR_RE.search(onclick or "")
            if m:
                self._link_pjmr = m.group(1)
                self._link_text = ""
                self._in_link = True

    def handle_data(self, data: str) -> None:
        if self._in_link:
            self._link_text += data.strip()

    def handle_endtag(self, tag: str) -> None:
        if tag == "a" and self._in_link:
            if self._link_pjmr and self._link_text:
                self.menu[self._link_text] = self._link_pjmr
            self._link_pjmr = None
            self._in_link = False

    def _handle_input(self, a: dict[str, str | None]) -> None:
        itype = (a.get("type") or "").lower()
        name = a.get("name") or ""
        value = a.get("value") or ""

        if itype == "hidden":
            if name == "PJ_Ext_Fld":
                self.ext_fields.append(value)
            else:
                self.hidden[name] = value
        elif itype == "text" and "date" in (a.get("onfocus") or "").lower():
            self.date_fields.append(name)
        elif itype == "button" and value == "Search":
            m = self._PJMR_RE.search(a.get("onclick") or "")
            if m:
                self.search_pjmr = m.group(1)


def _parse_form(html: str) -> _FormParser:
    p = _FormParser()
    p.feed(html)
    return p


# ---------------------------------------------------------------------------
# Table parsing
# ---------------------------------------------------------------------------

# Match the 4 consecutive data cells directly.  The row's action cell
# contains a nested <table> whose inner </tr> confuses row-based regexes,
# but the 4 data cells always appear together in this exact pattern.
_CELLS_RE = re.compile(
    r'<td class="pjr">([^<]+)</td>\s*'
    r'<td class="pjr">([^<]+)</td>\s*'
    r'<td class="pjr">([^<]+)</td>\s*'
    r'<td class="pjr align-right">([^<]+)</td>'
)


def _parse_usage_table(html: str) -> list[WaterUsageReading]:
    """Extract usage records from the results HTML table.

    Each data row has 4 data cells (after the action cell):
      Meter #, Service, Read Date/Time, Usage in Gallons

    The last row is a totals row with &nbsp; placeholders — skip it.
    """
    readings: list[WaterUsageReading] = []
    for meter, _service, dt_str, gallons_str in _CELLS_RE.findall(html):
        if "&nbsp;" in meter:
            continue  # totals row

        timestamp = datetime.strptime(dt_str.strip(), "%m/%d/%y %I:%M %p")
        readings.append(
            WaterUsageReading(
                timestamp=timestamp.replace(tzinfo=_TZ),
                usage_gallons=int(gallons_str.strip().replace(",", "")),
                meter_number=meter.strip(),
            )
        )

    readings.sort(key=lambda r: r.timestamp)
    return readings


# ---------------------------------------------------------------------------
# Form encoding
# ---------------------------------------------------------------------------


def _encode_form(fields: list[tuple[str, str]]) -> bytes:
    """URL-encode form fields using ISO-8859-1 (matching the server)."""
    parts = []
    for name, value in fields:
        enc_n = quote(name, safe="", encoding=FORM_CHARSET)
        enc_v = quote(value, safe="", encoding=FORM_CHARSET)
        parts.append(f"{enc_n}={enc_v}")
    return "&".join(parts).encode("ascii")


def _base_fields(hidden: dict[str, str], pjmr: str) -> list[tuple[str, str]]:
    """Build the common set of WOW form fields for a POST.

    PJ_SESSION_ID uses [] instead of .get() intentionally — a missing
    session ID is a caller bug and should raise KeyError immediately.
    """
    return [
        ("PJ_SESSION_ID", hidden["PJ_SESSION_ID"]),
        ("PJ_REQUEST_ID", hidden.get("PJ_REQUEST_ID", "0")),
        ("PJ_GROUP_ID", hidden.get("PJ_GROUP_ID", "0")),
        ("PJ_PAGE_ID", hidden.get("PJ_PAGE_ID", "0")),
        ("PJMR", pjmr),
        ("URLShortcutFilter", ""),
        ("_pj_lib", hidden.get("_pj_lib", "AQUASTAR")),
        ("ACTION_REQUESTED", ""),
        ("PJMRRC", ""),
        ("PJMRP1", ""),
        ("deappsid", hidden.get("deappsid", "0")),
        ("mdalias", hidden.get("mdalias", "DEFAULT")),
        ("opid", ""),
        ("_pjWinType", "0"),
    ]


# ---------------------------------------------------------------------------
# Main download logic
# ---------------------------------------------------------------------------


async def download_usage(
    sectoken: str,
    start_date: date,
    end_date: date,
) -> list[WaterUsageReading]:
    """Fetch hourly water usage for the given date range.

    Creates a fresh aiohttp session, then walks the WOW stateful form
    sequence:
      1. GET  with sectoken -> login, get session
      2. POST PJMR for "Water Usage by Hour" -> navigate to report
      3. POST with dates -> server runs query, returns HTML table

    Both dates are inclusive.

    Returns parsed WaterUsageReadings sorted ascending by timestamp.
    Raises AuthenticationError, CannotConnectError, or AquastarError.
    """
    connector = aiohttp.TCPConnector(
        resolver=aiohttp.ThreadedResolver(),
        ssl=_get_ssl_context(),
    )
    timeout = aiohttp.ClientTimeout(total=60)
    try:
        async with aiohttp.ClientSession(
            connector=connector,
            timeout=timeout,
        ) as session:
            return await _fetch(session, sectoken, start_date, end_date)
    except aiohttp.ClientResponseError as err:
        raise AquastarError(f"HTTP {err.status}: {err.message}") from err
    except (TimeoutError, OSError) as err:
        raise CannotConnectError(str(err)) from err


async def _fetch(
    session: aiohttp.ClientSession,
    sectoken: str,
    start_date: date,
    end_date: date,
) -> list[WaterUsageReading]:
    # Step 1: GET with sectoken (login)
    login_url = f"{RUN_URL}&sectoken={quote(sectoken, safe='')}"
    _LOGGER.debug("Getting PJ_SESSION_ID from sectoken")
    async with session.get(login_url) as resp:
        if resp.status != 200:
            raise AuthenticationError(f"Sectoken URL returned status {resp.status}")
        html = await resp.text(encoding=FORM_CHARSET)

    p1 = _parse_form(html)
    if "PJ_SESSION_ID" not in p1.hidden:
        raise AuthenticationError("No PJ_SESSION_ID in response")

    hourly_pjmr = p1.menu.get("Water Usage by Hour")
    if not hourly_pjmr:
        raise AquastarError(
            f"Cannot find 'Water Usage by Hour' menu item. Available: {list(p1.menu)}"
        )

    # Step 2: navigate to "Water Usage by Hour"
    body = _encode_form(_base_fields(p1.hidden, hourly_pjmr))
    _LOGGER.debug("Selecting Water Usage by Hour (%s)", hourly_pjmr)
    async with session.post(RUN_URL, data=body, headers=FORM_CT) as resp:
        resp.raise_for_status()
        html = await resp.text(encoding=FORM_CHARSET)

    p2 = _parse_form(html)
    if not p2.search_pjmr:
        raise AquastarError("No Search button found on hourly usage page")
    if len(p2.date_fields) < 2:
        raise AquastarError(f"Expected 2 date fields, found {p2.date_fields}")

    # Step 3: set date range and get results
    start_str = start_date.strftime("%m/%d/%Y")
    # The server includes start_date but excludes end_date (except
    # midnight), so bump by one day to include the full end date.
    end_str = (end_date + timedelta(days=1)).strftime("%m/%d/%Y")

    fields = _base_fields(p2.hidden, p2.search_pjmr)
    fields.append((p2.date_fields[0], start_str))
    fields.append(("PJ_Ext_Fld", p2.date_fields[0]))
    fields.append((p2.date_fields[1], end_str))
    fields.append(("PJ_Ext_Fld", p2.date_fields[1]))

    body = _encode_form(fields)
    _LOGGER.debug("Requesting readings %s to %s", start_str, end_str)
    async with session.post(RUN_URL, data=body, headers=FORM_CT) as resp:
        resp.raise_for_status()
        html = await resp.text(encoding=FORM_CHARSET)

    readings = _parse_usage_table(html)
    _LOGGER.debug("Found %d readings", len(readings))

    if not readings:
        _LOGGER.warning(
            "No usage records found — date range may be empty "
            "or page structure may have changed"
        )

    return readings


if __name__ == "__main__":
    import asyncio

    from typer import Option, run

    end = date.today()
    start = end - timedelta(days=1)

    def parse_date(x: date | str) -> date:
        return date.fromisoformat(str(x))

    def main(
        sectoken: Annotated[str, Option(envvar="SECTOKEN")],
        start: Annotated[date, Option(parser=parse_date)] = start,
        end: Annotated[date, Option(parser=parse_date)] = end,
        days: int = 0,
    ) -> None:
        """Fetch hourly water usage from Aquastar."""

        logging.basicConfig(level=logging.DEBUG)

        if days:
            start = end - timedelta(days=days)

        async def runner():
            return await download_usage(sectoken, start, end)

        records = asyncio.run(runner())

        for r in records:
            print(r)  # noqa

    run(main)
