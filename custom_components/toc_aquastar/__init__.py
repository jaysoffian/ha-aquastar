"""Town of Cary Aquastar integration."""

from __future__ import annotations

from homeassistant.core import HomeAssistant
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.recorder import get_instance

from .const import CONF_METER_NUMBER, CONF_SECTOKEN, DOMAIN
from .coordinator import AquastarConfigEntry, AquastarCoordinator

CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)


async def async_setup_entry(hass: HomeAssistant, entry: AquastarConfigEntry) -> bool:
    """Set up Aquastar from a config entry."""
    coordinator = AquastarCoordinator(
        hass, entry, entry.data[CONF_SECTOKEN], entry.data[CONF_METER_NUMBER]
    )
    await coordinator.async_config_entry_first_refresh()
    entry.runtime_data = coordinator

    return True


async def async_unload_entry(_hass: HomeAssistant, entry: AquastarConfigEntry) -> bool:
    """Unload a config entry."""
    return True


async def async_remove_entry(hass: HomeAssistant, entry: AquastarConfigEntry) -> None:
    """Remove a config entry — clear associated statistics."""
    meter_number = entry.data.get(CONF_METER_NUMBER, "")
    get_instance(hass).async_clear_statistics(
        [
            f"{DOMAIN}:{meter_number}_water_consumption",
            f"{DOMAIN}:{meter_number}_water_cost",
        ]
    )
