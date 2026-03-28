"""Town of Cary Aquastar integration."""

from __future__ import annotations

import aiohttp
from homeassistant.core import HomeAssistant
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.recorder import get_instance

from .client import AquastarClient, make_ssl_context
from .const import CONF_METER_NUMBER, CONF_SECTOKEN, DOMAIN
from .coordinator import AquastarConfigEntry, AquastarCoordinator

CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)


async def async_setup_entry(hass: HomeAssistant, entry: AquastarConfigEntry) -> bool:
    """Set up Aquastar from a config entry."""
    ssl_ctx = await hass.async_add_executor_job(make_ssl_context)
    connector = aiohttp.TCPConnector(ssl=ssl_ctx)
    timeout = aiohttp.ClientTimeout(total=30)
    websession = aiohttp.ClientSession(
        connector=connector, timeout=timeout, cookie_jar=aiohttp.DummyCookieJar()
    )

    try:
        client = AquastarClient(websession, sectoken=entry.data[CONF_SECTOKEN])
        coordinator = AquastarCoordinator(
            hass, client, entry, entry.data[CONF_METER_NUMBER], websession
        )
        await coordinator.async_config_entry_first_refresh()
    except Exception:
        await websession.close()
        raise
    entry.runtime_data = coordinator

    return True


async def async_unload_entry(_hass: HomeAssistant, entry: AquastarConfigEntry) -> bool:
    """Unload a config entry."""
    await entry.runtime_data.websession.close()
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
