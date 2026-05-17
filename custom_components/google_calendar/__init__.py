from __future__ import annotations

import logging
import os
from datetime import datetime, time
from typing import Any

import voluptuous as vol

from aiohttp import web

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import Flow
from googleapiclient.discovery import build

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.components.http import HomeAssistantView
from homeassistant.helpers import config_validation as cv
from homeassistant.util import dt as dt_util

from .const import (
    DOMAIN,
    CONF_CREDENTIALS_FILE,
    CONF_TOKEN_FILE,
    CONF_CALENDAR_ID,
    CONF_BASE_URL,
    CALLBACK_PATH,
    SCOPES,
)

_LOGGER = logging.getLogger(__name__)

SERVICE_START_OAUTH = "start_oauth"
SERVICE_DELETE_EVENTS = "delete_events"

START_OAUTH_SCHEMA = vol.Schema({})

DELETE_EVENTS_SCHEMA = vol.Schema(
    {
        vol.Required("start_date"): cv.string,
        vol.Required("end_date"): cv.string,
        vol.Required("summary_contains"): cv.string,
        vol.Optional("calendar_id"): cv.string,
        vol.Optional("dry_run", default=True): cv.boolean,
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


def _load_credentials(hass: HomeAssistant, token_file: str) -> Credentials:
    token_path = hass.config.path(token_file)

    if not os.path.exists(token_path):
        raise FileNotFoundError(
            f"Не найден token.json: {token_path}. "
            f"Сначала выполните сервис {DOMAIN}.start_oauth."
        )

    creds = Credentials.from_authorized_user_file(token_path, SCOPES)

    if not creds.valid:
        if creds.expired and creds.refresh_token:
            creds.refresh(Request())
            with open(token_path, "w", encoding="utf-8") as token:
                token.write(creds.to_json())
        else:
            raise RuntimeError(
                "Google token недействителен и не может быть обновлён. "
                f"Запустите сервис {DOMAIN}.start_oauth повторно."
            )

    return creds


def _get_calendar_service(hass: HomeAssistant, token_file: str):
    creds = _load_credentials(hass, token_file)
    return build("calendar", "v3", credentials=creds)


def _delete_events_sync(
    hass: HomeAssistant,
    token_file: str,
    calendar_id: str,
    start_date: str,
    end_date: str,
    summary_contains: str,
    dry_run: bool,
) -> dict[str, Any]:
    service = _get_calendar_service(hass, token_file)

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
                item = {
                    "id": event_id,
                    "summary": summary,
                    "start": start,
                }
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


def _create_oauth_url_sync(
    credentials_path: str,
    redirect_uri: str,
    state: str,
) -> tuple[str, Flow]:
    flow = Flow.from_client_secrets_file(
        credentials_path,
        scopes=SCOPES,
        redirect_uri=redirect_uri,
    )

    auth_url, _ = flow.authorization_url(
        access_type="offline",
        include_granted_scopes="true",
        prompt="consent",
        state=state,
    )

    return auth_url, flow


def _fetch_token_sync(flow: Flow, code: str, token_path: str) -> None:
    flow.fetch_token(code=code)
    creds = flow.credentials

    with open(token_path, "w", encoding="utf-8") as token:
        token.write(creds.to_json())


class GoogleCalendarOAuthCallbackView(HomeAssistantView):
    """OAuth callback endpoint."""

    url = CALLBACK_PATH
    name = "api:gcal_cleanup:oauth2callback"
    requires_auth = False

    def __init__(self, hass: HomeAssistant) -> None:
        self.hass = hass

    async def get(self, request: web.Request) -> web.Response:
        hass = request.app["hass"]

        error = request.query.get("error")
        code = request.query.get("code")
        state = request.query.get("state")

        if error:
            return web.Response(text=f"Google OAuth error: {error}", status=400)

        if not code or not state:
            return web.Response(
                text="OAuth callback error: отсутствует code или state.",
                status=400,
            )

        oauth_flows = hass.data.get(DOMAIN, {}).get("oauth_flows", {})
        oauth_data = oauth_flows.get(state)

        if oauth_data is None:
            return web.Response(
                text="OAuth callback error: неизвестный state.",
                status=400,
            )

        flow = oauth_data["flow"]
        token_path = oauth_data["token_path"]

        try:
            await hass.async_add_executor_job(_fetch_token_sync, flow, code, token_path)
            oauth_flows.pop(state, None)

            await hass.services.async_call(
                "persistent_notification",
                "create",
                {
                    "title": "Google Calendar авторизован",
                    "message": f"Файл token.json создан: `{token_path}`",
                    "notification_id": "gcal_cleanup_oauth_success",
                },
                blocking=False,
            )

            return web.Response(
                text=(
                    "<html><body>"
                    "<h2>Google Calendar авторизован</h2>"
                    "<p>token.json успешно создан. Эту вкладку можно закрыть.</p>"
                    "</body></html>"
                ),
                content_type="text/html",
            )

        except Exception as err:
            _LOGGER.exception("Ошибка завершения Google OAuth")
            await hass.services.async_call(
                "persistent_notification",
                "create",
                {
                    "title": "Ошибка Google Calendar OAuth",
                    "message": str(err),
                    "notification_id": "gcal_cleanup_oauth_error",
                },
                blocking=False,
            )
            return web.Response(text=f"Ошибка завершения OAuth: {err}", status=500)


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    hass.data.setdefault(DOMAIN, {})
    hass.data[DOMAIN].setdefault("entries", {})
    hass.data[DOMAIN].setdefault("oauth_flows", {})
    hass.data[DOMAIN]["entries"][entry.entry_id] = entry

    if not hass.data[DOMAIN].get("view_registered"):
        hass.http.register_view(GoogleCalendarOAuthCallbackView(hass))
        hass.data[DOMAIN]["view_registered"] = True

    async def handle_start_oauth(call: ServiceCall) -> None:
        credentials_file = entry.data[CONF_CREDENTIALS_FILE]
        token_file = entry.data[CONF_TOKEN_FILE]
        base_url = entry.data[CONF_BASE_URL]

        credentials_path = hass.config.path(credentials_file)
        token_path = hass.config.path(token_file)

        if not os.path.exists(credentials_path):
            await hass.services.async_call(
                "persistent_notification",
                "create",
                {
                    "title": "Google Calendar OAuth: credentials.json не найден",
                    "message": f"Файл не найден: `{credentials_path}`",
                    "notification_id": "gcal_cleanup_credentials_missing",
                },
                blocking=False,
            )
            return

        redirect_uri = f"{base_url}{CALLBACK_PATH}"
        state = entry.entry_id

        try:
            auth_url, flow = await hass.async_add_executor_job(
                _create_oauth_url_sync,
                credentials_path,
                redirect_uri,
                state,
            )

            hass.data[DOMAIN]["oauth_flows"][state] = {
                "flow": flow,
                "token_path": token_path,
            }

            await hass.services.async_call(
                "persistent_notification",
                "create",
                {
                    "title": "Авторизация Google Calendar",
                    "message": (
                        "Откройте ссылку и разрешите доступ к календарю:\n\n"
                        f"[Авторизовать Google Calendar]({auth_url})\n\n"
                        "Callback URL должен быть добавлен в Google Cloud:\n\n"
                        f"`{redirect_uri}`"
                    ),
                    "notification_id": "gcal_cleanup_oauth_start",
                },
                blocking=False,
            )

        except Exception as err:
            _LOGGER.exception("Ошибка запуска Google OAuth")
            await hass.services.async_call(
                "persistent_notification",
                "create",
                {
                    "title": "Ошибка запуска Google OAuth",
                    "message": str(err),
                    "notification_id": "gcal_cleanup_oauth_start_error",
                },
                blocking=False,
            )

    async def handle_delete_events(call: ServiceCall) -> None:
        token_file = entry.data[CONF_TOKEN_FILE]
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

            title = "Google Calendar: проверка удаления" if dry_run else "Google Calendar: события удалены"
            message = (
                f"Календарь: `{result['calendar_id']}`\n\n"
                f"Период: `{result['start_date']}` — `{result['end_date']}`\n\n"
                f"Поиск в summary: `{', '.join(result['summary_contains'])}`\n\n"
                f"Найдено: **{result['matched_count']}**\n\n"
                f"Удалено: **{result['deleted_count']}**\n\n"
            )

            if result["matched"]:
                message += "События:\n\n"
                for item in result["matched"]:
                    message += f"- {item['summary']} | {item['start']}\n"

            await hass.services.async_call(
                "persistent_notification",
                "create",
                {
                    "title": title,
                    "message": message,
                    "notification_id": "gcal_cleanup_delete_events",
                },
                blocking=False,
            )

            _LOGGER.info("Google Calendar cleanup result: %s", result)

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

    if not hass.services.has_service(DOMAIN, SERVICE_START_OAUTH):
        hass.services.async_register(
            DOMAIN,
            SERVICE_START_OAUTH,
            handle_start_oauth,
            schema=START_OAUTH_SCHEMA,
        )

    if not hass.services.has_service(DOMAIN, SERVICE_DELETE_EVENTS):
        hass.services.async_register(
            DOMAIN,
            SERVICE_DELETE_EVENTS,
            handle_delete_events,
            schema=DELETE_EVENTS_SCHEMA,
        )

    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    hass.data[DOMAIN]["entries"].pop(entry.entry_id, None)
    hass.data[DOMAIN]["oauth_flows"].pop(entry.entry_id, None)
    return True
