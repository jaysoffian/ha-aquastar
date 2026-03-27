"""CLI test tool: SECTOKEN=... uv run python -m custom_components.toc_aquastar.client"""

from __future__ import annotations

import asyncio
import os
from datetime import date, timedelta
from typing import Annotated

import aiohttp
import typer

from .client import AquastarClient, make_ssl_context

cli = typer.Typer()


def _parse_date(value: str) -> date:
    return date.fromisoformat(value)


def _get_sectoken() -> str:
    sectoken = os.environ.get("SECTOKEN", "")
    if not sectoken:
        typer.echo("Set SECTOKEN environment variable to your Aquastar sectoken")
        raise SystemExit(1)
    return sectoken


@cli.command()
def usage(
    start: Annotated[
        str | None,
        typer.Option(help="Start date (YYYY-MM-DD), default 3 days ago"),
    ] = None,
    end: Annotated[
        str | None,
        typer.Option(help="End date (YYYY-MM-DD), default today"),
    ] = None,
    days: Annotated[
        int,
        typer.Option(help="Number of days back from end (ignored if --start given)"),
    ] = 3,
) -> None:
    """Fetch hourly water usage from Aquastar."""
    sectoken = _get_sectoken()
    end_date = _parse_date(end) if end else date.today()
    start_date = _parse_date(start) if start else (end_date - timedelta(days=days))

    typer.echo(f"Fetching usage from {start_date} to {end_date}...")

    async def _run() -> None:
        ssl_context = make_ssl_context()
        resolver = aiohttp.ThreadedResolver()
        connector = aiohttp.TCPConnector(resolver=resolver, ssl=ssl_context)
        async with aiohttp.ClientSession(connector=connector) as session:
            client = AquastarClient(session, sectoken=sectoken)
            readings = await client.async_get_usage(start_date, end_date)

        typer.echo(f"Got {len(readings)} readings:")
        for r in readings:
            typer.echo(
                f"  {r.timestamp}  {r.usage_gallons:>5} gal  meter={r.meter_number}"
            )

    asyncio.run(_run())


if __name__ == "__main__":
    cli()
