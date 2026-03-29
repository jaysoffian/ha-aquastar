"""Coordinator for Aquastar water usage statistics."""

from __future__ import annotations

import logging
from collections.abc import Mapping, Sequence
from datetime import date, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

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
    AquastarError,
    AuthenticationError,
    WaterUsageReading,
    download_usage,
)
from .const import (
    BACKFILL_DAYS,
    CONF_BILLING_DAY,
    DEFAULT_BILLING_DAY,
    DOMAIN,
    UPDATE_INTERVAL_MINUTES,
)
from .rates import (
    calculate_interval_cost,
    get_rate_schedule,
)

_TZ = ZoneInfo("America/New_York")

_LOGGER = logging.getLogger(__name__)

type AquastarConfigEntry = ConfigEntry[AquastarCoordinator]


def billing_period(d: date, billing_day: int) -> tuple[int, int]:
    """Return a (year, month) tuple identifying which billing period *d* falls in.

    A billing period starts on *billing_day* and runs to the day before
    the next *billing_day*.  For ``billing_day=16``, Jan 16 through Feb 15
    is the "January" period ``(2026, 1)``, and Feb 16 onward is ``(2026, 2)``.

    When ``billing_day`` is 1 this collapses to normal calendar months.
    """
    if d.day >= billing_day:
        return (d.year, d.month)
    # Before the billing day — still in the prior period.
    first_of_month = d.replace(day=1)
    prev = first_of_month - timedelta(days=1)
    return (prev.year, prev.month)


def billing_period_start(d: date, billing_day: int) -> datetime:
    """Return the start-of-period datetime for the billing period containing *d*."""
    year, month = billing_period(d, billing_day)
    return datetime(year, month, billing_day, tzinfo=_TZ)


class AquastarCoordinator(DataUpdateCoordinator[None]):
    """Fetch water usage and insert external statistics."""

    config_entry: AquastarConfigEntry

    def __init__(
        self,
        hass: HomeAssistant,
        config_entry: AquastarConfigEntry,
        sectoken: str,
        meter_number: str,
    ) -> None:
        super().__init__(
            hass,
            _LOGGER,
            config_entry=config_entry,
            name="Aquastar",
            update_interval=timedelta(minutes=UPDATE_INTERVAL_MINUTES),
        )
        self._sectoken = sectoken
        self.meter_number = meter_number
        self._billing_day: int = int(
            config_entry.options.get(CONF_BILLING_DAY, DEFAULT_BILLING_DAY)
        )
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
            unit_class="volume",
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
            unit_class=None,
            unit_of_measurement="USD",
        )

    @staticmethod
    def build_cost_statistics(
        readings: list[WaterUsageReading],
        *,
        billing_day: int = DEFAULT_BILLING_DAY,
        starting_cost_sum: float = 0.0,
        starting_cumulative_period_gallons: float = 0.0,
        starting_period: tuple[int, int] | None = None,
    ) -> list[StatisticData]:
        """Derive cost statistics from readings.

        For a full backfill the defaults are correct (all zeros, no prior
        period).  For an incremental update, pass the running cost sum and
        the cumulative period-to-date consumption so that tier placement
        accounts for earlier readings in the same billing period.
        """
        cost_sum = starting_cost_sum
        cumulative_period_gallons = starting_cumulative_period_gallons
        current_period = starting_period
        stats: list[StatisticData] = []

        for reading in readings:
            period = billing_period(reading.timestamp.date(), billing_day)
            if period != current_period:
                cumulative_period_gallons = 0.0
                current_period = period

            schedule = get_rate_schedule(reading.timestamp.date())
            interval_cost = calculate_interval_cost(
                reading.usage_gallons, cumulative_period_gallons, schedule
            )
            cost_sum += interval_cost
            stats.append(
                StatisticData(
                    start=reading.timestamp,
                    state=interval_cost,
                    sum=cost_sum,
                )
            )
            cumulative_period_gallons += reading.usage_gallons

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
                cost_statistics = self.build_cost_statistics(
                    backfill_readings, billing_day=self._billing_day
                )
                _LOGGER.debug(
                    "Inserting %d cost statistics (sum=%.2f)",
                    len(cost_statistics),
                    cost_statistics[-1].get("sum", 0),
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
            prior_period_gallons = 0.0
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

            # Compute period-to-date consumption for tiered cost calculation.
            # Find the billing period start for the first new reading, then
            # query hourly statistics from that point to compute how many
            # gallons were already consumed in this billing period.
            period_start = billing_period_start(
                readings[0].timestamp.date(), self._billing_day
            )
            period_stats = await get_instance(self.hass).async_add_executor_job(
                statistics_during_period,
                self.hass,
                period_start - timedelta(hours=1),
                readings[0].timestamp,
                {self._statistic_id},
                "hour",
                None,
                {"sum"},
            )
            sum_at_period_start = 0.0
            if period_rows := period_stats.get(self._statistic_id):
                sum_at_period_start = float(period_rows[0].get("sum") or 0)
            prior_period_gallons = consumption_sum - sum_at_period_start

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

        # Build cost statistics with correct billing period tracking.
        first_period = billing_period(readings[0].timestamp.date(), self._billing_day)
        cost_statistics = self.build_cost_statistics(
            readings,
            billing_day=self._billing_day,
            starting_cost_sum=cost_sum,
            starting_cumulative_period_gallons=prior_period_gallons,
            starting_period=first_period,
        )

        _LOGGER.debug(
            "Inserting %d statistics (consumption_sum=%.0f, cost_sum=%.2f)",
            len(consumption_statistics),
            consumption_sum,
            cost_statistics[-1].get("sum", 0),
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
        _LOGGER.debug("Backfill fetching %s to %s", start, today)
        return self._filter_readings(await download_usage(self._sectoken, start, today))

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
        _LOGGER.debug("Incremental fetching %s to %s", start, today)
        readings = await download_usage(self._sectoken, start, today)
        return self._filter_readings([r for r in readings if r.timestamp > cutoff])
