from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timedelta, timezone
from typing import Any

import voluptuous as vol
from google.oauth2.credentials import Credentials

from homeassistant import config_entries
from homeassistant.config_entries import ConfigEntry, SOURCE_REAUTH
from homeassistant.helpers import config_entry_oauth2_flow
from homeassistant.helpers.selector import (
    SelectOptionDict,
    SelectSelector,
    SelectSelectorConfig,
)

from .api import list_task_lists
from .const import (
    DOMAIN,
    CONF_CREDENTIALS_FILE,
    CONF_TOKEN_FILE,
    CONF_CALENDAR_ID,
    CONF_TASK_LIST_ID,
    DEFAULT_CREDENTIALS_FILE,
    DEFAULT_TOKEN_FILE,
    DEFAULT_CALENDAR_ID,
    SCOPES,
)

_LOGGER = logging.getLogger(__name__)


class GoogleCalendarOAuth2Implementation(
    config_entry_oauth2_flow.LocalOAuth2Implementation
):
    """Google OAuth implementation using HA's native OAuth callback flow."""

    @property
    def extra_authorize_data(self) -> dict[str, str]:
        """Google-specific authorize parameters."""
        return {
            "scope": " ".join(SCOPES),
            "access_type": "offline",
            "prompt": "consent",
        }


def _read_google_client_secrets(credentials_path: str) -> dict[str, str]:
    """Read a Google OAuth web/installed client secrets file."""
    with open(credentials_path, encoding="utf-8") as file:
        raw = json.load(file)

    client = raw.get("web") or raw.get("installed")
    if not isinstance(client, dict):
        raise ValueError("credentials.json не содержит секцию web или installed")

    required = ("client_id", "client_secret", "auth_uri", "token_uri")
    missing = [key for key in required if not client.get(key)]
    if missing:
        raise ValueError(
            "В credentials.json отсутствуют поля: " + ", ".join(missing)
        )

    return {key: str(client[key]) for key in required}


def _write_google_token(
    token_path: str,
    token_data: dict[str, Any],
    client_data: dict[str, str],
) -> None:
    """Persist HA OAuth token in the Google authorized-user JSON format."""
    old_refresh_token: str | None = None
    if os.path.exists(token_path):
        try:
            with open(token_path, encoding="utf-8") as file:
                old_data = json.load(file)
            old_refresh_token = old_data.get("refresh_token")
        except (OSError, ValueError, TypeError):
            pass

    refresh_token = token_data.get("refresh_token") or old_refresh_token
    expires_in = int(token_data.get("expires_in", 3600))

    creds = Credentials(
        token=token_data["access_token"],
        refresh_token=refresh_token,
        token_uri=client_data["token_uri"],
        client_id=client_data["client_id"],
        client_secret=client_data["client_secret"],
        scopes=SCOPES,
    )
    creds.expiry = datetime.now(timezone.utc) + timedelta(seconds=expires_in)

    os.makedirs(os.path.dirname(token_path) or ".", exist_ok=True)
    with open(token_path, "w", encoding="utf-8") as file:
        file.write(creds.to_json())


class GoogleCalendarConfigFlow(
    config_entry_oauth2_flow.AbstractOAuth2FlowHandler, domain=DOMAIN
):
    """Config flow for Google Calendar using Home Assistant native OAuth UX."""

    DOMAIN = DOMAIN
    VERSION = 3

    def __init__(self) -> None:
        super().__init__()
        self._pending_entry_data: dict[str, Any] | None = None
        self._client_data: dict[str, str] | None = None

    @property
    def logger(self) -> logging.Logger:
        return _LOGGER

    @staticmethod
    def async_get_options_flow(config_entry: ConfigEntry) -> GoogleCalendarOptionsFlow:
        """Create the options flow."""
        return GoogleCalendarOptionsFlow()

    async def _async_prepare_oauth(
        self, credentials_file: str
    ) -> GoogleCalendarOAuth2Implementation:
        credentials_path = self.hass.config.path(credentials_file)
        self._client_data = await self.hass.async_add_executor_job(
            _read_google_client_secrets, credentials_path
        )
        return GoogleCalendarOAuth2Implementation(
            self.hass,
            DOMAIN,
            self._client_data["client_id"],
            self._client_data["client_secret"],
            self._client_data["auth_uri"],
            self._client_data["token_uri"],
        )

    async def async_step_user(self, user_input: dict[str, Any] | None = None):
        """Set up the integration and authorize Google immediately."""
        errors: dict[str, str] = {}

        if user_input is not None:
            credentials_path = self.hass.config.path(user_input[CONF_CREDENTIALS_FILE])

            if not os.path.exists(credentials_path):
                errors[CONF_CREDENTIALS_FILE] = "credentials_not_found"
            else:
                try:
                    self.flow_impl = await self._async_prepare_oauth(
                        user_input[CONF_CREDENTIALS_FILE]
                    )
                except (OSError, ValueError, TypeError) as err:
                    _LOGGER.error("Invalid Google credentials file: %s", err)
                    errors[CONF_CREDENTIALS_FILE] = "credentials_invalid"
                else:
                    await self.async_set_unique_id("gcal_cleanup")
                    self._abort_if_unique_id_configured()
                    self._pending_entry_data = {
                        CONF_CREDENTIALS_FILE: user_input[CONF_CREDENTIALS_FILE],
                        CONF_TOKEN_FILE: user_input[CONF_TOKEN_FILE],
                        CONF_CALENDAR_ID: user_input[CONF_CALENDAR_ID],
                    }
                    return await super().async_step_auth()

        schema = vol.Schema(
            {
                vol.Required(
                    CONF_CREDENTIALS_FILE, default=DEFAULT_CREDENTIALS_FILE
                ): str,
                vol.Required(CONF_TOKEN_FILE, default=DEFAULT_TOKEN_FILE): str,
                vol.Required(CONF_CALENDAR_ID, default=DEFAULT_CALENDAR_ID): str,
            }
        )

        return self.async_show_form(step_id="user", data_schema=schema, errors=errors)

    async def async_step_reauth(self, entry_data: dict[str, Any]):
        """Start native Home Assistant reauthentication."""
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(
        self, user_input: dict[str, Any] | None = None
    ):
        """Ask for confirmation, then use HA's standard external OAuth step."""
        if user_input is None:
            return self.async_show_form(
                step_id="reauth_confirm", data_schema=vol.Schema({})
            )

        entry_id = self.context.get("entry_id")
        entry = self.hass.config_entries.async_get_entry(entry_id) if entry_id else None
        if entry is None:
            return self.async_abort(reason="reauth_entry_missing")

        credentials_path = self.hass.config.path(entry.data[CONF_CREDENTIALS_FILE])
        if not os.path.exists(credentials_path):
            return self.async_show_form(
                step_id="reauth_confirm",
                data_schema=vol.Schema({}),
                errors={"base": "credentials_not_found"},
            )

        try:
            self.flow_impl = await self._async_prepare_oauth(
                entry.data[CONF_CREDENTIALS_FILE]
            )
        except (OSError, ValueError, TypeError) as err:
            _LOGGER.error("Invalid Google credentials file: %s", err)
            return self.async_show_form(
                step_id="reauth_confirm",
                data_schema=vol.Schema({}),
                errors={"base": "credentials_invalid"},
            )

        return await super().async_step_auth()

    async def async_oauth_create_entry(self, data: dict[str, Any]):
        """Save OAuth token and finish initial setup or reauthentication."""
        token_data = data["token"]

        if self.source == SOURCE_REAUTH:
            entry_id = self.context.get("entry_id")
            entry = self.hass.config_entries.async_get_entry(entry_id) if entry_id else None
            if entry is None:
                return self.async_abort(reason="reauth_entry_missing")

            if self._client_data is None:
                self._client_data = await self.hass.async_add_executor_job(
                    _read_google_client_secrets,
                    self.hass.config.path(entry.data[CONF_CREDENTIALS_FILE]),
                )

            await self.hass.async_add_executor_job(
                _write_google_token,
                self.hass.config.path(entry.data[CONF_TOKEN_FILE]),
                token_data,
                self._client_data,
            )

            self.hass.data.get(DOMAIN, {}).get("reauth_started", set()).discard(
                entry.entry_id
            )
            await self.hass.config_entries.async_reload(entry.entry_id)
            return self.async_abort(reason="reauth_successful")

        if self._pending_entry_data is None or self._client_data is None:
            return self.async_abort(reason="oauth_failed")

        await self.hass.async_add_executor_job(
            _write_google_token,
            self.hass.config.path(self._pending_entry_data[CONF_TOKEN_FILE]),
            token_data,
            self._client_data,
        )

        return self.async_create_entry(
            title="Google Calendar",
            data=self._pending_entry_data,
        )


class GoogleCalendarOptionsFlow(config_entries.OptionsFlowWithReload):
    """Options flow for selecting the Google Tasks list."""

    async def async_step_init(self, user_input: dict[str, Any] | None = None):
        """Manage integration options."""
        if user_input is not None:
            return self.async_create_entry(data=user_input)

        token_file = self.config_entry.data[CONF_TOKEN_FILE]
        current_task_list_id = self.config_entry.options.get(CONF_TASK_LIST_ID)
        errors: dict[str, str] = {}
        task_lists: list[dict[str, str]] = []

        try:
            task_lists = await self.hass.async_add_executor_job(
                list_task_lists,
                self.hass,
                token_file,
            )
        except FileNotFoundError:
            errors["base"] = "token_not_found"
        except Exception:
            errors["base"] = "tasks_unavailable"

        if not task_lists:
            return self.async_show_form(
                step_id="init",
                data_schema=vol.Schema({}),
                errors=errors or {"base": "no_task_lists"},
            )

        options: list[SelectOptionDict] = [
            SelectOptionDict(value=item["id"], label=item["title"])
            for item in task_lists
        ]
        available_ids = {item["id"] for item in task_lists}

        if current_task_list_id and current_task_list_id not in available_ids:
            options.append(
                SelectOptionDict(
                    value=current_task_list_id,
                    label=f"Недоступный список ({current_task_list_id})",
                )
            )

        suggested = current_task_list_id or task_lists[0]["id"]
        schema = vol.Schema(
            {
                vol.Required(
                    CONF_TASK_LIST_ID,
                    description={"suggested_value": suggested},
                ): SelectSelector(
                    SelectSelectorConfig(options=options, multiple=False)
                )
            }
        )

        return self.async_show_form(step_id="init", data_schema=schema, errors=errors)
