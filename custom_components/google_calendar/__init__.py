from __future__ import annotations

import logging
import os
from datetime import datetime, time
from typing import Any

import voluptuous as vol
from google.oauth2.credentials import Credentials

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant, ServiceCall, SupportsResponse
from homeassistant.helpers import config_validation as cv
from homeassistant.util import dt as dt_util

from .api import get_calendar_service
from .const import (
    CONF_CALENDAR_ID,
    CONF_TOKEN_FILE,
    DOMAIN,
    SCOPES,
)

_LOGGER = logging.getLogger(__name__)

PLATFORMS = [Platform.SENSOR]
SERVICE_DELETE_EVENTS = "delete_events"

DELETE_EVENTS_SCHEMA = vol.Schema(
    {
        vol.Required("start_date"): cv.string,
        vol.Required("end_date"): cv.string,
        vol.Required("summary_contains"): cv.string,
        vol.Optional("calendar_id"): cv.string,
        vol.Optional("dry_run", default=False): cv.boolean,
    }
)


def _parse_local_datetime(value: str, is_end: bool = False) -> str:
    value = value.strip()

    if len(value) == 10:
        date_obj = datetime.strptime(value, "%Y-%m-%d").date()
        dt_obj = datetime.combine(
            date_obj,
            time(23, 59, 59) if is_end else time(0, 0, 0),
        )
    else:
        dt_obj = dt_util.parse_datetime(value)
        if dt_obj is None:
            raise ValueError(f"Некорректная дата/время: {value}")

    if dt_obj.tzinfo is None:
        dt_obj = dt_obj.replace(tzinfo=dt_util.DEFAULT_TIME_ZONE)

    return dt_obj.isoformat()


def _delete_events_sync(
    hass: HomeAssistant,
    token_file: str,
    calendar_id: str,
    start_date: str,
    end_date: str,
    summary_contains: str,
    dry_run: bool,
) -> dict[str, Any]:
    service = get_calendar_service(hass, token_file)

    time_min = _parse_local_datetime(start_date, is_end=False)
    time_max = _parse_local_datetime(end_date, is_end=True)
    search_terms = [item.strip() for item in summary_contains.split(",") if item.strip()]

    if not search_terms:
        raise ValueError("Поле summary_contains пустое.")

    matched = []
    deleted = []
    page_token = None

    while True:
        events_result = (
            service.events()
            .list(
                calendarId=calendar_id,
                timeMin=time_min,
                timeMax=time_max,
                singleEvents=True,
                orderBy="startTime",
                maxResults=2500,
                pageToken=page_token,
            )
            .execute()
        )

        events = events_result.get("items", [])
        for event in events:
            summary = event.get("summary", "")
            event_id = event.get("id")
            start = event.get("start", {})

            if not event_id:
                continue

            if any(term in summary for term in search_terms):
                item = {"id": event_id, "summary": summary, "start": start}
                matched.append(item)

                if not dry_run:
                    service.events().delete(
                        calendarId=calendar_id,
                        eventId=event_id,
                    ).execute()
                    deleted.append(item)

        page_token = events_result.get("nextPageToken")
        if not page_token:
            break

    return {
        "calendar_id": calendar_id,
        "start_date": start_date,
        "end_date": end_date,
        "summary_contains": search_terms,
        "dry_run": dry_run,
        "matched_count": len(matched),
        "deleted_count": len(deleted),
        "matched": matched,
        "deleted": deleted,
    }



def _token_requires_reauth_sync(
    hass: HomeAssistant,
    token_file: str,
) -> bool:
    """Return True when the stored Google token is missing, invalid, or lacks required scopes."""
    token_path = hass.config.path(token_file)

    if not os.path.exists(token_path):
        return True

    try:
        creds = Credentials.from_authorized_user_file(token_path)
    except (OSError, ValueError, TypeError):
        return True

    if not creds.has_scopes(SCOPES):
        return True

    if creds.valid:
        return False

    if creds.expired and creds.refresh_token:
        try:
            from google.auth.transport.requests import Request

            creds.refresh(Request())
            with open(token_path, "w", encoding="utf-8") as token:
                token.write(creds.to_json())
            return False
        except Exception:  # noqa: BLE001 - refresh failure must trigger HA reauth
            _LOGGER.exception("Не удалось обновить Google OAuth token")
            return True

    return True


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Google Calendar custom integration from a config entry."""
    hass.data.setdefault(DOMAIN, {})
    hass.data[DOMAIN].setdefault("entries", {})
    hass.data[DOMAIN].setdefault("reauth_started", set())
    hass.data[DOMAIN]["entries"][entry.entry_id] = entry

    token_file = entry.data[CONF_TOKEN_FILE]
    needs_reauth = await hass.async_add_executor_job(
        _token_requires_reauth_sync,
        hass,
        token_file,
    )
    if needs_reauth and entry.entry_id not in hass.data[DOMAIN]["reauth_started"]:
        hass.data[DOMAIN]["reauth_started"].add(entry.entry_id)
        entry.async_start_reauth_if_available(hass)

    async def handle_delete_events(call: ServiceCall) -> dict[str, Any] | None:
        calendar_id = call.data.get(
            "calendar_id",
            entry.data.get(CONF_CALENDAR_ID, "primary"),
        )
        start_date = call.data["start_date"]
        end_date = call.data["end_date"]
        summary_contains = call.data["summary_contains"]
        dry_run = call.data["dry_run"]

        try:
            result = await hass.async_add_executor_job(
                _delete_events_sync,
                hass,
                token_file,
                calendar_id,
                start_date,
                end_date,
                summary_contains,
                dry_run,
            )

            _LOGGER.info("Google Calendar cleanup result: %s", result)

            # Home Assistant покажет этот ответ прямо в
            # Инструментарий разработчика -> Действия.
            # Для вызовов без запроса ответа (например из автоматизации)
            # ничего дополнительно не создаём.
            if call.return_response:
                return result
            return None

        except Exception as err:
            _LOGGER.exception("Ошибка удаления событий Google Calendar")
            await hass.services.async_call(
                "persistent_notification",
                "create",
                {
                    "title": "Ошибка Google Calendar Cleanup",
                    "message": str(err),
                    "notification_id": "gcal_cleanup_delete_error",
                },
                blocking=False,
            )
            return None

    if not hass.services.has_service(DOMAIN, SERVICE_DELETE_EVENTS):
        hass.services.async_register(
            DOMAIN,
            SERVICE_DELETE_EVENTS,
            handle_delete_events,
            schema=DELETE_EVENTS_SCHEMA,
            supports_response=SupportsResponse.OPTIONAL,
        )

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload Google Calendar custom integration."""
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if not unload_ok:
        return False

    hass.data[DOMAIN]["entries"].pop(entry.entry_id, None)
    hass.data[DOMAIN].get("reauth_started", set()).discard(entry.entry_id)

    if not hass.data[DOMAIN]["entries"]:
        hass.services.async_remove(DOMAIN, SERVICE_DELETE_EVENTS)

    return True
