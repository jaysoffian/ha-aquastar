# CLAUDE.md

## Git
- Do NOT include Claude attribution in commit messages.
- Always verify `git status` is clean before making changes.

## Verification
- Run: `pre-commit run --all`

## Python
- Always use `uv` to run Python, pytest, and tools (never bare `python` or `python3`).
- Always use `uv add` and `uv remove` to add or remove Python packages.
- Never add new `pyright: ignore` or `type: ignore` comments — needing one means the approach is wrong.

## Project overview
- Home Assistant custom integration for Town of Cary Aquastar water usage monitoring.
- Client code lives in `custom_components/toc_aquastar/client/` — standalone async aiohttp client.
- HA integration code lives in `custom_components/toc_aquastar/` alongside the client package.
- Runtime dependency: `xlrd` (for parsing CDFV2 .xls files from the portal). Listed in `manifest.json` requirements.

## Aquastar portal
- Built by PlanetJ on their WOW platform.
- Auth: stable `sectoken` (tied to account, doesn't change across logins).
- Session: `JSESSIONID` + `wow.user` JWT cookie (~14 day validity).
- Navigation: server-side page state with dynamic PJMR action codes.
- Data: hourly water usage in gallons, downloaded as XLS (CDFV2 format).
- HTML encoding: both pages are iso-8859-1 (`charset=iso-8859-1` in meta tag). Read with `encoding="iso-8859-1"`.
- Date field names use `¤` (U+00A4) prefix: `¤{prefix}_4` (start), `¤{prefix}_5` (end).
- `PJ_Ext_Fld` appears twice in form POST (once per date field) — handled by custom iso-8859-1 URL encoder (not `aiohttp.FormData`).

## Test fixtures
- `tests/fixtures/dashboard.html` — synthetic dashboard HTML (tests page state + menu parsing)
- `tests/fixtures/hourly.html` — synthetic hourly page HTML, iso-8859-1 encoded (tests date field + XLS link parsing)
- `tests/fixtures/usage.xls` — synthetic XLS with fake meter data (tests XLS parser)
