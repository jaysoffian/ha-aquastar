# CLAUDE.md

## Setup (run once per environment)
On the user's local machine, `uv` and `prek` are already installed. Do not reinstall them.

When running in a cloud/container environment (e.g. Claude Code on the web), upgrade or install `uv` and `prek` first:
- `pip install --upgrade uv prek`

Then: `uv sync && prek install`

## Git
- Do NOT include Claude attribution in commit messages.
- Always verify `git status` is clean before making changes.

## Verification
- Run: `prek run --all-files`
- Never run ruff, pyright, or other linting/type-checking tools directly — prek manages its own environments for these.

## Python
- Always use `uv` to run Python, pytest, and tools (never bare `python` or `python3`).
- Always use `uv add` and `uv remove` to add or remove Python packages.
- Never add new `pyright: ignore` or `type: ignore` comments — needing one means the approach is wrong.

## Project overview
- Home Assistant custom integration for Town of Cary Aquastar water usage monitoring.
- Client code lives in `custom_components/toc_aquastar/client.py` — standalone async aiohttp client.
- HA integration code lives in `custom_components/toc_aquastar/` alongside the client module.

## Test fixtures
- `tests/fixtures/dashboard.html` — synthetic dashboard HTML (tests page state + menu parsing)
- `tests/fixtures/hourly.html` — synthetic hourly page HTML, iso-8859-1 encoded (tests date field + search button parsing)
- `tests/fixtures/results.html` — synthetic results HTML table (tests usage record parsing)
