from __future__ import annotations

import os
from typing import Any

import voluptuous as vol

from homeassistant import config_entries

from .const import (
    DOMAIN,
    CONF_CREDENTIALS_FILE,
    CONF_TOKEN_FILE,
    CONF_CALENDAR_ID,
    CONF_BASE_URL,
    DEFAULT_CREDENTIALS_FILE,
    DEFAULT_TOKEN_FILE,
    DEFAULT_CALENDAR_ID,
)


class GoogleCalendarConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Config flow for Google Calendar Cleanup."""

    VERSION = 1

    async def async_step_user(self, user_input: dict[str, Any] | None = None):
        errors: dict[str, str] = {}

        if user_input is not None:
            credentials_path = self.hass.config.path(
                user_input[CONF_CREDENTIALS_FILE]
            )

            if not os.path.exists(credentials_path):
                errors[CONF_CREDENTIALS_FILE] = "credentials_not_found"
            else:
                await self.async_set_unique_id("gcal_cleanup")
                self._abort_if_unique_id_configured()

                return self.async_create_entry(
                    title="Google Calendar Cleanup",
                    data={
                        CONF_CREDENTIALS_FILE: user_input[CONF_CREDENTIALS_FILE],
                        CONF_TOKEN_FILE: user_input[CONF_TOKEN_FILE],
                        CONF_CALENDAR_ID: user_input[CONF_CALENDAR_ID],
                        CONF_BASE_URL: user_input[CONF_BASE_URL].rstrip("/"),
                    },
                )

        schema = vol.Schema(
            {
                vol.Required(
                    CONF_CREDENTIALS_FILE,
                    default=DEFAULT_CREDENTIALS_FILE,
                ): str,
                vol.Required(
                    CONF_TOKEN_FILE,
                    default=DEFAULT_TOKEN_FILE,
                ): str,
                vol.Required(
                    CONF_CALENDAR_ID,
                    default=DEFAULT_CALENDAR_ID,
                ): str,
                vol.Required(
                    CONF_BASE_URL,
                    default="http://homeassistant.local:8123",
                ): str,
            }
        )

        return self.async_show_form(
            step_id="user",
            data_schema=schema,
            errors=errors,
        )
