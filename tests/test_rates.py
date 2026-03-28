"""Tests for the water rate calculation module."""

from datetime import date, datetime
from zoneinfo import ZoneInfo

import pytest

from custom_components.toc_aquastar.client import WaterUsageReading
from custom_components.toc_aquastar.coordinator import AquastarCoordinator
from custom_components.toc_aquastar.rates import (
    RATE_SCHEDULES,
    RateSchedule,
    calculate_interval_cost,
    calculate_monthly_base_fee,
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


class TestMonthlyBaseFee:
    def test_current(self) -> None:
        assert calculate_monthly_base_fee(date(2026, 1, 1)) == 4.09

    def test_prior(self) -> None:
        assert calculate_monthly_base_fee(date(2025, 6, 30)) == 3.93


def _reading(ts: datetime, gallons: int) -> WaterUsageReading:
    return WaterUsageReading(timestamp=ts, meter_number="M1", usage_gallons=gallons)


# Current schedule cost for N gallons at tier 1 with sewer
def _t1_cost(gallons: int) -> float:
    return gallons * (5.46 + _SEWER) / 1000


# Current schedule cost for N gallons at tier 2 with sewer
def _t2_cost(gallons: int) -> float:
    return gallons * (6.13 + _SEWER) / 1000


_BASE = 4.09  # current monthly base fee


class TestBuildCostStatistics:
    """Test AquastarCoordinator.build_cost_statistics."""

    def test_backfill_from_zero(self) -> None:
        """Full backfill: base fee on first reading of each month."""
        readings = [
            _reading(datetime(2026, 1, 15, 10, tzinfo=_TZ), 100),
            _reading(datetime(2026, 1, 15, 11, tzinfo=_TZ), 200),
            _reading(datetime(2026, 2, 1, 0, tzinfo=_TZ), 50),
        ]
        stats = AquastarCoordinator.build_cost_statistics(readings)
        assert len(stats) == 3
        assert "state" in stats[0] and "sum" in stats[0]
        assert "state" in stats[1] and "sum" in stats[1]
        assert "state" in stats[2] and "sum" in stats[2]
        # First reading includes base fee
        assert stats[0]["state"] == pytest.approx(_BASE + _t1_cost(100))
        # Second reading: no base fee
        assert stats[1]["state"] == pytest.approx(_t1_cost(200))
        # New month: base fee again
        assert stats[2]["state"] == pytest.approx(_BASE + _t1_cost(50))

    def test_incremental_with_prior_month_consumption(self) -> None:
        """Incremental update mid-month: no base fee, correct tier."""
        readings = [
            _reading(datetime(2026, 1, 20, 14, tzinfo=_TZ), 100),
        ]
        # With 5000 gallons already consumed — tier 2, base fee already applied
        stats = AquastarCoordinator.build_cost_statistics(
            readings,
            starting_cost_sum=10.0,
            starting_cumulative_month_gallons=5000,
            starting_month=(2026, 1),
            base_fee_already_applied=True,
        )
        assert "state" in stats[0] and "sum" in stats[0]
        assert stats[0]["state"] == pytest.approx(_t2_cost(100))
        assert stats[0]["sum"] == pytest.approx(10.0 + _t2_cost(100))

    def test_incremental_new_month_gets_base_fee(self) -> None:
        """Incremental update at month boundary adds base fee."""
        readings = [
            _reading(datetime(2026, 2, 1, 0, tzinfo=_TZ), 100),
        ]
        # starting_month is January, reading is February — new month
        stats = AquastarCoordinator.build_cost_statistics(
            readings,
            starting_cost_sum=10.0,
            starting_cumulative_month_gallons=3000,
            starting_month=(2026, 1),
            base_fee_already_applied=True,
        )
        assert "state" in stats[0]
        assert stats[0]["state"] == pytest.approx(_BASE + _t1_cost(100))

    def test_incremental_month_boundary_resets_cumulative(self) -> None:
        """When readings span a month boundary, the new month resets to 0."""
        readings = [
            _reading(datetime(2026, 1, 31, 23, tzinfo=_TZ), 100),
            _reading(datetime(2026, 2, 1, 0, tzinfo=_TZ), 100),
        ]
        stats = AquastarCoordinator.build_cost_statistics(
            readings,
            starting_cost_sum=5.0,
            starting_cumulative_month_gallons=6000,
            starting_month=(2026, 1),
            base_fee_already_applied=True,
        )
        assert "state" in stats[0] and "state" in stats[1]
        # January reading: cumulative 6000, tier 2, no base fee (already applied)
        assert stats[0]["state"] == pytest.approx(_t2_cost(100))
        # February reading: cumulative resets, tier 1, base fee added
        assert stats[1]["state"] == pytest.approx(_BASE + _t1_cost(100))
