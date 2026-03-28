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
    statistics_during_period,
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
from .rates import (
    calculate_interval_cost,
    calculate_monthly_base_fee,
    get_rate_schedule,
)

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
        self._cost_statistic_id = f"{DOMAIN}:{meter_number}_water_cost"

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

    @property
    def _consumption_metadata(self) -> StatisticMetaData:
        return StatisticMetaData(
            mean_type=StatisticMeanType.NONE,
            has_mean=False,
            has_sum=True,
            name=f"Aquastar {self.meter_number} Water Consumption",
            source=DOMAIN,
            statistic_id=self._statistic_id,
            unit_of_measurement=UnitOfVolume.GALLONS,
        )

    @property
    def _cost_metadata(self) -> StatisticMetaData:
        return StatisticMetaData(
            mean_type=StatisticMeanType.NONE,
            has_mean=False,
            has_sum=True,
            name=f"Aquastar {self.meter_number} Water Cost",
            source=DOMAIN,
            statistic_id=self._cost_statistic_id,
            unit_of_measurement="USD",
        )

    @staticmethod
    def build_cost_statistics(
        readings: list[WaterUsageReading],
        *,
        starting_cost_sum: float = 0.0,
        starting_cumulative_month_gallons: float = 0.0,
        starting_month: tuple[int, int] | None = None,
        base_fee_already_applied: bool = False,
    ) -> list[StatisticData]:
        """Derive cost statistics from readings.

        For a full backfill the defaults are correct (all zeros, no prior
        month).  For an incremental update, pass the running cost sum and
        the cumulative month-to-date consumption so that tier placement
        accounts for earlier readings in the same month.

        The monthly base fee is added to the first reading of each new
        calendar month.  Set *base_fee_already_applied* when resuming
        mid-month so the base fee isn't double-counted.
        """
        cost_sum = starting_cost_sum
        cumulative_month_gallons = starting_cumulative_month_gallons
        current_month = starting_month
        month_base_applied = base_fee_already_applied
        stats: list[StatisticData] = []

        for reading in readings:
            reading_month = (reading.timestamp.year, reading.timestamp.month)
            if reading_month != current_month:
                cumulative_month_gallons = 0.0
                current_month = reading_month
                month_base_applied = False

            interval_cost = 0.0
            if not month_base_applied:
                interval_cost += calculate_monthly_base_fee(reading.timestamp.date())
                month_base_applied = True

            schedule = get_rate_schedule(reading.timestamp.date())
            interval_cost += calculate_interval_cost(
                reading.usage_gallons, cumulative_month_gallons, schedule
            )
            cost_sum += interval_cost
            stats.append(
                StatisticData(
                    start=reading.timestamp,
                    state=interval_cost,
                    sum=cost_sum,
                )
            )
            cumulative_month_gallons += reading.usage_gallons

        return stats

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
        last_cost_stat = await get_instance(self.hass).async_add_executor_job(
            get_last_statistics,
            self.hass,
            1,
            self._cost_statistic_id,
            True,
            {"sum"},
        )

        has_consumption = bool(last_stat)
        has_cost = bool(last_cost_stat.get(self._cost_statistic_id))

        # If consumption exists but cost was cleared (e.g. to recalculate
        # after a rate update), rebuild cost from a fresh backfill.
        if has_consumption and not has_cost:
            _LOGGER.info("Cost statistics missing — rebuilding from backfill data")
            backfill_readings = await self._async_backfill()
            if backfill_readings:
                cost_statistics = self.build_cost_statistics(backfill_readings)
                assert "sum" in cost_statistics[-1]
                _LOGGER.debug(
                    "Inserting %d cost statistics (sum=%.2f)",
                    len(cost_statistics),
                    cost_statistics[-1]["sum"],
                )
                async_add_external_statistics(
                    self.hass, self._cost_metadata, cost_statistics
                )
            # Fall through to normal update for any new readings.

        if not has_consumption:
            _LOGGER.info("No existing statistics — starting backfill")
            readings = await self._async_backfill()
            if not readings:
                _LOGGER.debug("Backfill returned no readings")
                return
            consumption_sum = 0.0
            cost_sum = 0.0
            prior_month_gallons = 0.0
            last_stat_month: tuple[int, int] | None = None
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
            last_start = stat_row.get("start")
            assert last_start is not None
            last_stat_dt = datetime.fromtimestamp(last_start, tz=_TZ)
            last_stat_month = (last_stat_dt.year, last_stat_dt.month)

            # Compute month-to-date consumption for tiered cost calculation.
            # The difference between consumption_sum and the running sum at
            # the start of the first reading's month tells us how many
            # gallons were already consumed this month.
            first_month_start = readings[0].timestamp.replace(
                day=1, hour=0, minute=0, second=0, microsecond=0
            )
            prev_month_stats = await get_instance(self.hass).async_add_executor_job(
                statistics_during_period,
                self.hass,
                first_month_start - timedelta(days=32),
                first_month_start,
                {self._statistic_id},
                "month",
                None,
                {"sum"},
            )
            sum_at_month_start = 0.0
            if prev_rows := prev_month_stats.get(self._statistic_id):
                sum_at_month_start = float(prev_rows[-1].get("sum") or 0)
            prior_month_gallons = consumption_sum - sum_at_month_start

            # Re-fetch cost stat in case it was just rebuilt above.
            if not has_cost:
                last_cost_stat = await get_instance(self.hass).async_add_executor_job(
                    get_last_statistics,
                    self.hass,
                    1,
                    self._cost_statistic_id,
                    True,
                    {"sum"},
                )
            cost_row = (last_cost_stat.get(self._cost_statistic_id) or [{}])[0]
            cost_sum = float(cost_row.get("sum") or 0)

        # Build consumption statistics and collect per-day totals for logging.
        consumption_statistics: list[StatisticData] = []
        day_counts: dict[date, int] = {}
        day_totals: dict[date, float] = {}
        for reading in readings:
            consumption_sum += reading.usage_gallons
            consumption_statistics.append(
                StatisticData(
                    start=reading.timestamp,
                    state=reading.usage_gallons,
                    sum=consumption_sum,
                )
            )
            d = reading.timestamp.date()
            day_counts[d] = day_counts.get(d, 0) + 1
            day_totals[d] = day_totals.get(d, 0) + reading.usage_gallons
        for d in sorted(day_counts):
            _LOGGER.debug(
                "Day %s: %d readings, %.0f gallons",
                d,
                day_counts[d],
                day_totals[d],
            )

        # Build cost statistics with correct cumulative month tracking.
        # The base fee was already applied if the last recorded stat is in
        # the same month as the first new reading.
        first_month = (readings[0].timestamp.year, readings[0].timestamp.month)
        cost_statistics = self.build_cost_statistics(
            readings,
            starting_cost_sum=cost_sum,
            starting_cumulative_month_gallons=prior_month_gallons,
            starting_month=first_month,
            base_fee_already_applied=last_stat_month == first_month,
        )

        assert "sum" in cost_statistics[-1]
        _LOGGER.debug(
            "Inserting %d statistics (consumption_sum=%.0f, cost_sum=%.2f)",
            len(consumption_statistics),
            consumption_sum,
            cost_statistics[-1]["sum"],
        )
        async_add_external_statistics(
            self.hass, self._consumption_metadata, consumption_statistics
        )
        async_add_external_statistics(self.hass, self._cost_metadata, cost_statistics)

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
        # Portal end date is exclusive, so use tomorrow to include today.
        end = today + timedelta(days=1)
        _LOGGER.debug("Backfill fetching %s to %s", start, end)
        return self._filter_readings(await self.client.async_get_usage(start, end))

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
        today = datetime.now(_TZ).date()
        if start > today:
            return []
        # Portal end date is exclusive, so use tomorrow to include today.
        end = today + timedelta(days=1)
        _LOGGER.debug("Incremental fetching %s to %s", start, end)
        readings = await self.client.async_get_usage(start, end)
        return self._filter_readings([r for r in readings if r.timestamp > cutoff])
