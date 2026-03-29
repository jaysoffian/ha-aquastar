"""Tests for the water rate calculation module."""

from datetime import date, datetime
from zoneinfo import ZoneInfo

import pytest

from custom_components.toc_aquastar.client import WaterUsageReading
from custom_components.toc_aquastar.coordinator import (
    AquastarCoordinator,
    billing_period,
)
from custom_components.toc_aquastar.rates import (
    RATE_SCHEDULES,
    RateSchedule,
    calculate_interval_cost,
    get_rate_schedule,
)

_TZ = ZoneInfo("America/New_York")

# Current schedule (FY2026): water tiers 5.46/6.13/7.74, sewer 11.69
_SEWER = 11.69  # current sewer rate per kgal
_PRIOR_SEWER = 11.24


class TestGetRateSchedule:
    """Test rate schedule lookup by date."""

    def test_current_rates(self) -> None:
        assert get_rate_schedule(date(2025, 7, 1)) is RATE_SCHEDULES[0]
        assert get_rate_schedule(date(2026, 1, 15)) is RATE_SCHEDULES[0]

    def test_prior_rates(self) -> None:
        assert get_rate_schedule(date(2025, 6, 30)) is RATE_SCHEDULES[1]
        assert get_rate_schedule(date(2024, 7, 1)) is RATE_SCHEDULES[1]

    def test_before_all_schedules(self) -> None:
        """Dates before all schedules fall back to the oldest."""
        assert get_rate_schedule(date(2020, 1, 1)) is RATE_SCHEDULES[-1]


class TestCalculateIntervalCost:
    """Test tiered water + flat sewer cost calculations."""

    @pytest.fixture
    def current_schedule(self) -> RateSchedule:
        return RATE_SCHEDULES[0]

    @pytest.fixture
    def prior_schedule(self) -> RateSchedule:
        return RATE_SCHEDULES[1]

    def test_tier1_only(self, current_schedule: RateSchedule) -> None:
        """100 gallons entirely in tier 1."""
        cost = calculate_interval_cost(100, 0, current_schedule)
        assert cost == pytest.approx(100 * (5.46 + _SEWER) / 1000)

    def test_tier1_at_boundary(self, current_schedule: RateSchedule) -> None:
        """Exactly at the tier 1 boundary (5000 gallons cumulative)."""
        cost = calculate_interval_cost(100, 4900, current_schedule)
        assert cost == pytest.approx(100 * (5.46 + _SEWER) / 1000)

    def test_crosses_tier1_to_tier2(self, current_schedule: RateSchedule) -> None:
        """200 gallons that cross from tier 1 into tier 2."""
        cost = calculate_interval_cost(200, 4900, current_schedule)
        water = 100 * 5.46 / 1000 + 100 * 6.13 / 1000
        sewer = 200 * _SEWER / 1000
        assert cost == pytest.approx(water + sewer)

    def test_tier2_only(self, current_schedule: RateSchedule) -> None:
        """Entirely in tier 2."""
        cost = calculate_interval_cost(100, 5500, current_schedule)
        assert cost == pytest.approx(100 * (6.13 + _SEWER) / 1000)

    def test_crosses_tier2_to_tier3(self, current_schedule: RateSchedule) -> None:
        """300 gallons that cross from tier 2 into tier 3."""
        cost = calculate_interval_cost(300, 7800, current_schedule)
        water = 200 * 6.13 / 1000 + 100 * 7.74 / 1000
        sewer = 300 * _SEWER / 1000
        assert cost == pytest.approx(water + sewer)

    def test_tier3_only(self, current_schedule: RateSchedule) -> None:
        """Entirely in tier 3."""
        cost = calculate_interval_cost(500, 10000, current_schedule)
        assert cost == pytest.approx(500 * (7.74 + _SEWER) / 1000)

    def test_crosses_all_tiers(self, current_schedule: RateSchedule) -> None:
        """Single large reading that spans all three tiers."""
        cost = calculate_interval_cost(10000, 0, current_schedule)
        water = 5000 * 5.46 / 1000 + 3000 * 6.13 / 1000 + 2000 * 7.74 / 1000
        sewer = 10000 * _SEWER / 1000
        assert cost == pytest.approx(water + sewer)

    def test_zero_usage(self, current_schedule: RateSchedule) -> None:
        cost = calculate_interval_cost(0, 3000, current_schedule)
        assert cost == 0.0

    def test_prior_rates_tier1(self, prior_schedule: RateSchedule) -> None:
        """Verify prior rate schedule is used correctly."""
        cost = calculate_interval_cost(100, 0, prior_schedule)
        assert cost == pytest.approx(100 * (5.25 + _PRIOR_SEWER) / 1000)


def _reading(ts: datetime, gallons: int) -> WaterUsageReading:
    return WaterUsageReading(timestamp=ts, meter_number="M1", usage_gallons=gallons)


# Current schedule cost for N gallons at tier 1 with sewer
def _t1_cost(gallons: int) -> float:
    return gallons * (5.46 + _SEWER) / 1000


# Current schedule cost for N gallons at tier 2 with sewer
def _t2_cost(gallons: int) -> float:
    return gallons * (6.13 + _SEWER) / 1000


class TestBillingPeriod:
    """Test billing_period helper."""

    def test_day1_is_calendar_month(self) -> None:
        assert billing_period(date(2026, 1, 1), 1) == (2026, 1)
        assert billing_period(date(2026, 1, 31), 1) == (2026, 1)
        assert billing_period(date(2026, 2, 1), 1) == (2026, 2)

    def test_day16_on_or_after(self) -> None:
        assert billing_period(date(2026, 1, 16), 16) == (2026, 1)
        assert billing_period(date(2026, 1, 31), 16) == (2026, 1)
        assert billing_period(date(2026, 2, 15), 16) == (2026, 1)

    def test_day16_before(self) -> None:
        assert billing_period(date(2026, 1, 15), 16) == (2025, 12)
        assert billing_period(date(2026, 1, 1), 16) == (2025, 12)

    def test_year_boundary(self) -> None:
        assert billing_period(date(2026, 1, 5), 16) == (2025, 12)
        assert billing_period(date(2025, 12, 16), 16) == (2025, 12)


class TestBuildCostStatistics:
    """Test AquastarCoordinator.build_cost_statistics."""

    def test_backfill_calendar_month(self) -> None:
        """With billing_day=1, tier resets on calendar month boundary."""
        readings = [
            _reading(datetime(2026, 1, 15, 10, tzinfo=_TZ), 100),
            _reading(datetime(2026, 1, 15, 11, tzinfo=_TZ), 200),
            _reading(datetime(2026, 2, 1, 0, tzinfo=_TZ), 50),
        ]
        stats = AquastarCoordinator.build_cost_statistics(readings)
        assert len(stats) == 3
        assert "state" in stats[0] and "state" in stats[1] and "state" in stats[2]
        assert stats[0]["state"] == pytest.approx(_t1_cost(100))
        assert stats[1]["state"] == pytest.approx(_t1_cost(200))
        assert stats[2]["state"] == pytest.approx(_t1_cost(50))

    def test_billing_day_16_reset(self) -> None:
        """With billing_day=16, tier resets on the 16th, not the 1st."""
        readings = [
            # Dec 16 period: these two accumulate together
            _reading(datetime(2026, 1, 10, 10, tzinfo=_TZ), 100),
            _reading(datetime(2026, 1, 15, 11, tzinfo=_TZ), 200),
            # Jan 16 period: new billing period resets cumulative
            _reading(datetime(2026, 1, 16, 0, tzinfo=_TZ), 50),
        ]
        stats = AquastarCoordinator.build_cost_statistics(readings, billing_day=16)
        assert len(stats) == 3
        assert "state" in stats[0] and "state" in stats[1] and "state" in stats[2]
        assert stats[0]["state"] == pytest.approx(_t1_cost(100))
        assert stats[1]["state"] == pytest.approx(_t1_cost(200))
        # New billing period — cumulative resets
        assert stats[2]["state"] == pytest.approx(_t1_cost(50))

    def test_billing_day_16_no_reset_at_calendar_month(self) -> None:
        """With billing_day=16, the calendar month boundary does NOT reset."""
        readings = [
            _reading(datetime(2026, 1, 31, 23, tzinfo=_TZ), 100),
            # Feb 1 is still in the Jan 16 billing period
            _reading(datetime(2026, 2, 1, 0, tzinfo=_TZ), 100),
        ]
        stats = AquastarCoordinator.build_cost_statistics(
            readings,
            billing_day=16,
            starting_cost_sum=5.0,
            starting_cumulative_period_gallons=6000,
            starting_period=(2026, 1),
        )
        assert "state" in stats[0] and "state" in stats[1]
        # Both readings in the same billing period — cumulative carries over
        assert stats[0]["state"] == pytest.approx(_t2_cost(100))
        assert stats[1]["state"] == pytest.approx(_t2_cost(100))

    def test_incremental_with_prior_period_consumption(self) -> None:
        """Incremental update mid-period: correct tier placement."""
        readings = [
            _reading(datetime(2026, 1, 20, 14, tzinfo=_TZ), 100),
        ]
        stats = AquastarCoordinator.build_cost_statistics(
            readings,
            starting_cost_sum=10.0,
            starting_cumulative_period_gallons=5000,
            starting_period=(2026, 1),
        )
        assert "state" in stats[0] and "sum" in stats[0]
        assert stats[0]["state"] == pytest.approx(_t2_cost(100))
        assert stats[0]["sum"] == pytest.approx(10.0 + _t2_cost(100))
