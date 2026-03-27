"""Coordinator for Aquastar water usage statistics."""

from __future__ import annotations

import logging
from collections.abc import Mapping, Sequence
from datetime import date, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

import aiohttp
from homeassistant.components.recorder.models import (
    StatisticData,
    StatisticMeanType,
    StatisticMetaData,
)
from homeassistant.components.recorder.statistics import (
    async_add_external_statistics,
    get_last_statistics,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import UnitOfVolume
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.recorder import get_instance
from homeassistant.helpers.update_coordinator import (
    DataUpdateCoordinator,
    UpdateFailed,
)

from .client import (
    AquastarClient,
    AquastarError,
    AuthenticationError,
    WaterUsageReading,
)
from .const import BACKFILL_DAYS, DOMAIN, UPDATE_INTERVAL_MINUTES

_TZ = ZoneInfo("America/New_York")

_LOGGER = logging.getLogger(__name__)

type AquastarConfigEntry = ConfigEntry[AquastarCoordinator]


class AquastarCoordinator(DataUpdateCoordinator[None]):
    """Fetch water usage and insert external statistics."""

    config_entry: AquastarConfigEntry

    def __init__(
        self,
        hass: HomeAssistant,
        client: AquastarClient,
        config_entry: AquastarConfigEntry,
        meter_number: str,
        websession: aiohttp.ClientSession,
    ) -> None:
        super().__init__(
            hass,
            _LOGGER,
            config_entry=config_entry,
            name="Aquastar",
            update_interval=timedelta(minutes=UPDATE_INTERVAL_MINUTES),
        )
        self.client = client
        self.meter_number = meter_number
        self.websession = websession
        self._statistic_id = f"{DOMAIN}:{meter_number}_water_consumption"

        @callback
        def _dummy_listener() -> None:
            pass

        # This integration has no entities, so no real listeners will be
        # registered. Without at least one listener the coordinator skips
        # scheduled refreshes. This dummy keeps periodic updates running.
        self.async_add_listener(_dummy_listener)

    async def _async_update_data(self) -> None:
        """Fetch new readings and insert statistics."""
        try:
            await self._async_update_statistics()
        except AuthenticationError as err:
            raise ConfigEntryAuthFailed from err
        except AquastarError as err:
            raise UpdateFailed(str(err)) from err

    async def _async_update_statistics(self) -> None:
        """Fetch and insert statistics (called by _async_update_data)."""
        last_stat = await get_instance(self.hass).async_add_executor_job(
            get_last_statistics,
            self.hass,
            1,
            self._statistic_id,
            True,
            {"sum"},
        )

        if not last_stat:
            _LOGGER.info("No existing statistics — starting backfill")
            readings = await self._async_backfill()
            if not readings:
                _LOGGER.debug("Backfill returned no readings")
                return
            consumption_sum = 0.0
        else:
            stat_row = last_stat[self._statistic_id][0]
            _LOGGER.debug(
                "Incremental update — last_stat: start=%s, sum=%s",
                stat_row.get("start"),
                stat_row.get("sum"),
            )
            readings = await self._async_incremental_fetch(last_stat)
            if not readings:
                _LOGGER.debug("No new readings")
                return
            last_sum = stat_row.get("sum")
            if last_sum is None:
                _LOGGER.error(
                    "Last statistic has no sum value — skipping update to"
                    " avoid corrupting the running total"
                )
                return
            consumption_sum = float(last_sum)

        # Log per-day reading counts
        day_counts: dict[date, int] = {}
        day_totals: dict[date, float] = {}
        for r in readings:
            d = r.timestamp.date()
            day_counts[d] = day_counts.get(d, 0) + 1
            day_totals[d] = day_totals.get(d, 0) + r.usage_gallons
        for d in sorted(day_counts):
            _LOGGER.debug(
                "Day %s: %d readings, %.0f gallons",
                d,
                day_counts[d],
                day_totals[d],
            )

        statistics = []
        first_sum = 0.0
        for reading in readings:
            consumption_sum += reading.usage_gallons
            if not statistics:
                first_sum = consumption_sum
            statistics.append(
                StatisticData(
                    start=reading.timestamp,
                    state=reading.usage_gallons,
                    sum=consumption_sum,
                )
            )

        metadata = StatisticMetaData(
            mean_type=StatisticMeanType.NONE,
            has_mean=False,
            has_sum=True,
            name=f"Aquastar {self.meter_number} Water Consumption",
            source=DOMAIN,
            statistic_id=self._statistic_id,
            unit_of_measurement=UnitOfVolume.GALLONS,
        )

        _LOGGER.debug(
            "Inserting %d statistics (first_sum=%.0f, last_sum=%.0f) for %s",
            len(statistics),
            first_sum,
            consumption_sum,
            self._statistic_id,
        )
        async_add_external_statistics(self.hass, metadata, statistics)

    def _filter_readings(
        self, readings: list[WaterUsageReading]
    ) -> list[WaterUsageReading]:
        """Keep only readings for this entry's meter number."""
        filtered = [r for r in readings if r.meter_number == self.meter_number]
        if len(filtered) < len(readings):
            _LOGGER.debug(
                "Filtered %d readings for other meters",
                len(readings) - len(filtered),
            )
        return filtered

    async def _async_backfill(self) -> list[WaterUsageReading]:
        """Fetch all available historical data in a single request."""
        today = datetime.now(_TZ).date()
        start = today - timedelta(days=BACKFILL_DAYS)
        _LOGGER.debug("Backfill fetching %s to %s", start, today)
        return self._filter_readings(await self.client.async_get_usage(start, today))

    async def _async_incremental_fetch(
        self, last_stat: Mapping[str, Sequence[Mapping[str, Any]]]
    ) -> list[WaterUsageReading]:
        """Fetch from the last recorded stat's day through today.

        Portal data has a ~day delay, so today's readings may not be
        available yet. Re-fetches the last stat's day to pick up any
        hours that were missing.
        """
        last_start = last_stat[self._statistic_id][0]["start"]
        last_dt = datetime.fromtimestamp(last_start, tz=_TZ)
        cutoff = last_dt
        start = last_dt.date()
        end = datetime.now(_TZ).date()
        if start > end:
            return []
        _LOGGER.debug("Incremental fetching %s to %s", start, end)
        readings = await self.client.async_get_usage(start, end)
        return self._filter_readings([r for r in readings if r.timestamp > cutoff])
