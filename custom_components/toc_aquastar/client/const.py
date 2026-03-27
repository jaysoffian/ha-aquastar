"""Constants for the Aquastar client."""

from typing import Final

BASE_URL: Final = "https://aquastar.townofcary.org"
ENDPOINT_RUN: Final = "/waterconsumption/run"

TIMEZONE: Final = "America/New_York"

# PlanetJ WOW form constants
PJ_LIB: Final = "AQUASTAR"

# Default headers to mimic a browser
DEFAULT_HEADERS: Final[dict[str, str]] = {
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
    "Origin": BASE_URL,
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/605.1.15 (KHTML, like Gecko) "
        "Version/26.3.1 Safari/605.1.15"
    ),
}

# Regex patterns for HTML parsing
# Extracts value from: <input type="hidden" name="PJ_SESSION_ID" value="..." />
RE_PJ_SESSION_ID: Final = r'name="PJ_SESSION_ID"\s+value="([^"]+)"'

# Extracts value from: <input type="hidden" name="PJ_GROUP_ID" value="..." />
RE_PJ_GROUP_ID: Final = r'name="PJ_GROUP_ID"\s+value="([^"]+)"'

# Extracts value from: <input type="hidden" name="PJ_PAGE_ID" value="..." />
RE_PJ_PAGE_ID: Final = r'name="PJ_PAGE_ID"\s+value="([^"]+)"'

# Extracts PJMR code from menu item by link text.
# e.g. onclick="return performMagic('PJMR11')">Water Usage by Hour</a>
RE_MENU_ITEM: Final = r"""performMagic\('(PJMR\d+)'\)">Water Usage by Hour</a>"""

# Extracts date field prefix from: name="¤{prefix}_4"
# The ¤ character (U+00A4) appears as \xc2\xa4 in UTF-8
RE_DATE_FIELD_PREFIX: Final = r'name="\u00a4(\d+)_4"'

# Extracts Search PJMR from: performMagic('URLShortcutFilterPJMR14')
# The JS strips the "URLShortcutFilter" prefix; we capture just the PJMR code.
RE_SEARCH_PJMR: Final = r"""performMagic\('URLShortcutFilter(PJMR\d+)'\)"""

# Extracts XLS download PJMR from: performMagic('PJMR17', '_blank')
# with spreadsheet.png nearby
RE_XLS_PJMR: Final = r"""performMagic\('(PJMR\d+)',\s*'_blank'\)"""

# JWT refresh buffer — re-establish session when JWT has less than this remaining
JWT_REFRESH_BUFFER_HOURS: Final = 24
