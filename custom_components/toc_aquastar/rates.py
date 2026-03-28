"""Town of Cary single-family residential utility rate schedules.

Inside Cary/Morrisville/RTP corporate limits, 1" or smaller meter.
Rates are per 1,000 gallons unless noted.
Source: https://www.carync.gov/home/showpublisheddocument/34256/638899023757300000
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date


@dataclass(frozen=True)
class RateTier:
    """A single tier in the water rate schedule.

    *upper_bound_gallons* is the cumulative monthly usage at which this
    tier stops applying.  ``None`` means the tier has no upper limit.
    """

    upper_bound_gallons: int | None
    rate_per_1000_gallons: float


@dataclass(frozen=True)
class RateSchedule:
    """Complete rate schedule with an effective date."""

    effective_date: date
    monthly_base_fee: float
    water_tiers: tuple[RateTier, ...]
    sewer_rate_per_1000_gallons: float


# Schedules ordered newest-first so the lookup can stop at the first match.
RATE_SCHEDULES: tuple[RateSchedule, ...] = (
    # Effective July 1, 2025
    RateSchedule(
        effective_date=date(2025, 7, 1),
        monthly_base_fee=4.09,
        water_tiers=(
            RateTier(upper_bound_gallons=5_000, rate_per_1000_gallons=5.46),
            RateTier(upper_bound_gallons=8_000, rate_per_1000_gallons=6.13),
            RateTier(upper_bound_gallons=None, rate_per_1000_gallons=7.74),
        ),
        sewer_rate_per_1000_gallons=11.69,
    ),
    # Effective July 1, 2024
    RateSchedule(
        effective_date=date(2024, 7, 1),
        monthly_base_fee=3.93,
        water_tiers=(
            RateTier(upper_bound_gallons=5_000, rate_per_1000_gallons=5.25),
            RateTier(upper_bound_gallons=8_000, rate_per_1000_gallons=5.89),
            RateTier(upper_bound_gallons=None, rate_per_1000_gallons=7.44),
        ),
        sewer_rate_per_1000_gallons=11.24,
    ),
)


def get_rate_schedule(usage_date: date) -> RateSchedule:
    """Return the rate schedule in effect on *usage_date*."""
    for schedule in RATE_SCHEDULES:
        if usage_date >= schedule.effective_date:
            return schedule
    # Fallback to the oldest schedule for historical data.
    return RATE_SCHEDULES[-1]


def calculate_interval_cost(
    usage_gallons: float,
    cumulative_month_gallons: float,
    schedule: RateSchedule,
) -> float:
    """Compute the water + sewer cost for a single hourly reading.

    *cumulative_month_gallons* is the total gallons consumed in the billing
    month *before* this reading.  The water portion may span multiple
    tiers if cumulative usage crosses a tier boundary.  Sewer is a flat
    per-1,000-gallon rate on all usage.
    """
    cost = 0.0
    remaining = usage_gallons

    # Tiered water charge.
    cumulative = cumulative_month_gallons
    for tier in schedule.water_tiers:
        if remaining <= 0:
            break
        if tier.upper_bound_gallons is not None:
            space_in_tier = max(0.0, tier.upper_bound_gallons - cumulative)
            gallons_in_tier = min(remaining, space_in_tier)
        else:
            gallons_in_tier = remaining

        cost += gallons_in_tier * tier.rate_per_1000_gallons / 1_000.0
        remaining -= gallons_in_tier
        cumulative += gallons_in_tier

    # Flat sewer charge on all gallons.
    cost += usage_gallons * schedule.sewer_rate_per_1000_gallons / 1_000.0

    return cost


def calculate_monthly_base_fee(usage_date: date) -> float:
    """Return the monthly base fee for the given date."""
    return get_rate_schedule(usage_date).monthly_base_fee
