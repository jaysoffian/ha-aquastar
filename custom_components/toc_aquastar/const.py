"""Constants for the Town of Cary Aquastar integration."""

from typing import Final

DOMAIN: Final = "toc_aquastar"

CONF_SECTOKEN: Final = "sectoken"
CONF_METER_NUMBER: Final = "meter_number"
CONF_BILLING_DAY: Final = "billing_day"

DEFAULT_BILLING_DAY: Final = 1

UPDATE_INTERVAL_MINUTES: Final = 30
BACKFILL_DAYS: Final = 450
