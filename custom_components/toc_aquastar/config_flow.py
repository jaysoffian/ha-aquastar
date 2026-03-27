"""Config flow for Town of Cary Aquastar integration."""

from __future__ import annotations

import logging
from collections.abc import Mapping
from datetime import datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

import aiohttp
import voluptuous as vol
from homeassistant import config_entries
from homeassistant.config_entries import ConfigFlowResult

from .client import (
    AquastarClient,
    AquastarError,
    AuthenticationError,
    CannotConnectError,
    make_ssl_context,
)
from .client.const import TIMEZONE
from .const import CONF_METER_NUMBER, CONF_SECTOKEN, DOMAIN

_LOGGER = logging.getLogger(__name__)

STEP_USER_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_SECTOKEN): str,
    }
)


class AquastarConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Aquastar."""

    VERSION = 1

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Handle sectoken configuration."""
        errors: dict[str, str] = {}

        if user_input is not None:
            sectoken = user_input[CONF_SECTOKEN].strip()
            meter_number, error = await self._async_validate_sectoken(sectoken)

            if error:
                errors["base"] = error
            else:
                await self.async_set_unique_id(meter_number)
                self._abort_if_unique_id_configured()
                return self.async_create_entry(
                    title=f"Aquastar ({meter_number})",
                    data={
                        CONF_SECTOKEN: sectoken,
                        CONF_METER_NUMBER: meter_number,
                    },
                )

        return self.async_show_form(
            step_id="user",
            data_schema=STEP_USER_SCHEMA,
            errors=errors,
        )

    async def async_step_reauth(
        self, entry_data: Mapping[str, Any]
    ) -> ConfigFlowResult:
        """Handle re-authentication when the sectoken becomes invalid."""
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Handle user input for re-authentication."""
        errors: dict[str, str] = {}

        if user_input is not None:
            sectoken = user_input[CONF_SECTOKEN].strip()
            reauth_entry = self._get_reauth_entry()
            meter_number, error = await self._async_validate_sectoken(sectoken)

            if error:
                errors["base"] = error
            elif meter_number != reauth_entry.data[CONF_METER_NUMBER]:
                errors["base"] = "meter_mismatch"
            else:
                return self.async_update_reload_and_abort(
                    reauth_entry,
                    data={
                        **reauth_entry.data,
                        CONF_SECTOKEN: sectoken,
                    },
                )

        return self.async_show_form(
            step_id="reauth_confirm",
            data_schema=STEP_USER_SCHEMA,
            errors=errors,
        )

    async def _async_validate_sectoken(
        self, sectoken: str
    ) -> tuple[str, None] | tuple[None, str]:
        """Validate the sectoken by fetching recent data.

        Returns (meter_number, None) on success, or (None, error_key).
        """
        ssl_ctx = await self.hass.async_add_executor_job(make_ssl_context)
        connector = aiohttp.TCPConnector(ssl=ssl_ctx)
        try:
            timeout = aiohttp.ClientTimeout(total=30)
            # No DummyCookieJar needed here (unlike the long-lived runtime
            # session) — this session is discarded after a single validation
            # call, so the jar can't accumulate stale cookies across refreshes.
            async with aiohttp.ClientSession(
                connector=connector, timeout=timeout
            ) as session:
                client = AquastarClient(session, sectoken=sectoken)
                end = datetime.now(ZoneInfo(TIMEZONE)).date()
                start = end - timedelta(days=7)
                readings = await client.async_get_usage(start, end)

                if not readings:
                    _LOGGER.error("No readings returned during validation")
                    return None, "no_readings"

                return readings[0].meter_number, None

        except AuthenticationError:
            _LOGGER.error("Invalid sectoken")
            return None, "invalid_auth"
        except CannotConnectError:
            _LOGGER.error("Cannot connect to Aquastar portal")
            return None, "cannot_connect"
        except AquastarError:
            _LOGGER.exception("Unexpected Aquastar error during validation")
            return None, "unknown"
