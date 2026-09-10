from __future__ import annotations

import os
from datetime import date, datetime, timedelta, timezone
from typing import Any, Sequence

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build

from homeassistant.core import HomeAssistant
from homeassistant.util import dt as dt_util

from .const import (
    CALENDAR_SCOPES,
    CONTACTS_BIRTHDAYS_CALENDAR_ID,
    DOMAIN,
    HOLIDAYS_CALENDAR_ID,
    TASKS_SCOPES,
)

_MONTHS_RU = [
    "января",
    "февраля",
    "марта",
    "апреля",
    "мая",
    "июня",
    "июля",
    "августа",
    "сентября",
    "октября",
    "ноября",
    "декабря",
]

_SKIP_EVENT_KEYWORDS = (
    "день рождения",
    "День рождения",
    "Именины",
    "Годовщина смерти",
)

_TERMINAL_PUNCTUATION = (".", ",", "?", "!")


def load_credentials(
    hass: HomeAssistant,
    token_file: str,
    required_scopes: Sequence[str],
) -> Credentials:
    """Load and refresh OAuth credentials from token.json."""
    token_path = hass.config.path(token_file)

    if not os.path.exists(token_path):
        raise FileNotFoundError(
            f"Не найден token.json: {token_path}. "
            "Требуется авторизация Google. Откройте интеграцию Google Calendar в Home Assistant и выполните повторную авторизацию."
        )

    # Do not inject new scopes into an old token while loading it. The token
    # itself contains the scopes that were actually granted by Google.
    creds = Credentials.from_authorized_user_file(token_path)

    if not creds.has_scopes(required_scopes):
        missing = ", ".join(required_scopes)
        raise RuntimeError(
            "Google token не содержит необходимые права доступа: "
            f"{missing}. Требуется повторная авторизация интеграции Google Calendar."
        )

    if not creds.valid:
        if creds.expired and creds.refresh_token:
            creds.refresh(Request())
            with open(token_path, "w", encoding="utf-8") as token:
                token.write(creds.to_json())
        else:
            raise RuntimeError(
                "Google token недействителен и не может быть обновлён. "
                "Требуется повторная авторизация интеграции Google Calendar."
            )

    return creds


def get_calendar_service(hass: HomeAssistant, token_file: str):
    creds = load_credentials(hass, token_file, CALENDAR_SCOPES)
    return build("calendar", "v3", credentials=creds)


def get_tasks_service(hass: HomeAssistant, token_file: str):
    creds = load_credentials(hass, token_file, TASKS_SCOPES)
    return build("tasks", "v1", credentials=creds)


def _to_rfc3339_utc(value: datetime) -> str:
    if value.tzinfo is None:
        value = value.replace(tzinfo=dt_util.DEFAULT_TIME_ZONE)
    value = value.astimezone(timezone.utc)
    return value.isoformat().replace("+00:00", "Z")


def _local_day_bounds() -> tuple[datetime, datetime]:
    now = dt_util.now()
    start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    return start, start + timedelta(days=1)


def _append_period_if_needed(value: str) -> str:
    if not value:
        return value
    if value[-1] in _TERMINAL_PUNCTUATION:
        return value
    return value + "."


def _plural_ru(count: int, one: str, few: str, many: str) -> str:
    if 11 <= count % 100 <= 14:
        return many
    if count % 10 == 1:
        return one
    if 2 <= count % 10 <= 4:
        return few
    return many


def _event_datetime(value: str) -> datetime:
    parsed = dt_util.parse_datetime(value)
    if parsed is None:
        raise ValueError(f"Некорректный формат dateTime: {value}")
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=dt_util.DEFAULT_TIME_ZONE)
    return dt_util.as_local(parsed)


def _format_today_event(event: dict[str, Any], today: date) -> str | None:
    summary = (event.get("summary") or "Без заголовка").rstrip()
    if any(keyword in summary for keyword in _SKIP_EVENT_KEYWORDS):
        return None

    start_data = event.get("start", {})
    end_data = event.get("end", {})
    start = start_data.get("dateTime") or start_data.get("date")
    end = end_data.get("dateTime") or end_data.get("date")

    if not start or not end:
        return summary

    # All-day event. Google end date is exclusive.
    if len(start) == 10 and len(end) == 10:
        start_date = date.fromisoformat(start)
        end_date_exclusive = date.fromisoformat(end)
        total_days = max(1, (end_date_exclusive - start_date).days)
        day_number = max(1, (today - start_date).days + 1)

        if total_days > 1:
            return f"Весь день: {summary} ({day_number}-й день из {total_days})"
        return f"Весь день: {summary}"

    if "T" not in start or "T" not in end:
        return f"Ошибка формата даты: {start}. Правильный формат - YYYY-MM-DDTHH:MM:SSZ."

    start_dt = _event_datetime(start)
    end_dt = _event_datetime(end)
    start_date = start_dt.date()
    end_date = end_dt.date()

    if start_date == today and end_date == today:
        return f"С {start_dt:%H:%M} до {end_dt:%H:%M}: {summary}"

    total_days = max(1, (end_date - start_date).days + 1)
    day_number = max(1, (today - start_date).days + 1)
    description = f"({day_number}-й день из {total_days})"

    if start_date == today and end_date > today:
        return f"С {start_dt:%H:%M} до 00:00: {summary} {description}"

    if end_date == today and start_date < today:
        return f"С 00:00 до {end_dt:%H:%M}: {summary} {description}"

    return f"Весь день: {summary} {description}"


def fetch_events(
    hass: HomeAssistant,
    token_file: str,
    calendar_id: str,
) -> dict[str, str]:
    """Return today's primary-calendar events in the old sensor format."""
    service = get_calendar_service(hass, token_file)
    now_local = dt_util.now()
    _, end_local = _local_day_bounds()

    result = (
        service.events()
        .list(
            calendarId=calendar_id,
            timeMin=_to_rfc3339_utc(now_local),
            timeMax=_to_rfc3339_utc(end_local),
            maxResults=50,
            singleEvents=True,
            orderBy="startTime",
        )
        .execute()
    )

    lines: list[str] = []
    for event in result.get("items", []):
        line = _format_today_event(event, now_local.date())
        if line is None:
            continue
        lines.append(_append_period_if_needed(line))

    count = len(lines)
    if count == 0:
        return {
            "state": "Сегодня нет мероприятий.",
            "text": "Сегодня нет мероприятий.",
        }

    word = _plural_ru(count, "мероприятие", "мероприятия", "мероприятий")
    count_state: str | int = "одно" if count == 1 else count
    body = "\n".join(f"{idx}. {line}" for idx, line in enumerate(lines, start=1))

    return {
        "state": f"На сегодня запланировано {count_state} {word}.",
        "text": f"\nНа сегодня запланировано {count_state} {word}:\n{body}\n\n",
    }


def _fetch_day_calendar(
    hass: HomeAssistant,
    token_file: str,
    calendar_id: str,
) -> list[dict[str, Any]]:
    service = get_calendar_service(hass, token_file)
    start_local, end_local = _local_day_bounds()
    result = (
        service.events()
        .list(
            calendarId=calendar_id,
            timeMin=_to_rfc3339_utc(start_local),
            timeMax=_to_rfc3339_utc(end_local),
            maxResults=50,
            singleEvents=True,
            orderBy="startTime",
        )
        .execute()
    )
    return result.get("items", [])


def fetch_holidays(hass: HomeAssistant, token_file: str) -> dict[str, str]:
    """Return today's Russian holidays in the old sensor format."""
    events = _fetch_day_calendar(hass, token_file, HOLIDAYS_CALENDAR_ID)
    lines = [
        _append_period_if_needed(f"- {(event.get('summary') or 'Без заголовка').rstrip()}")
        for event in events
    ]
    count = len(lines)

    if count == 0:
        return {
            "state": "Сегодня нет праздников.",
            "text": "Сегодня нет праздников.",
        }

    out = "\n".join(lines) + "\n"
    if count == 1:
        value = f"Сегодня {out}"
        return {"state": value, "text": value}

    word = _plural_ru(count, "праздник", "праздника", "праздников")
    value = f"Сегодня {count} {word}:\n{out}"
    return {"state": value, "text": value}


def fetch_contacts_birthdays(hass: HomeAssistant, token_file: str) -> dict[str, str]:
    """Return today's birthdays/events from the Google Contacts calendar."""
    events = _fetch_day_calendar(hass, token_file, CONTACTS_BIRTHDAYS_CALENDAR_ID)
    lines: list[str] = []

    for event in events:
        summary = (event.get("summary") or "Без заголовка").rstrip()
        description = (event.get("description") or "").rstrip()
        value = description if "день рождения" in description else summary
        lines.append(_append_period_if_needed(value))

    count = len(lines)
    if count == 0:
        return {
            "state": "Сегодня нет событий.",
            "text": "Сегодня нет событий.",
        }

    out = "\n".join(f"{idx}. {line}" for idx, line in enumerate(lines, start=1)) + "\n"

    if count == 1:
        single = lines[0]
        value = f"Сегодня одно событие: {single}\n"
        return {"state": value, "text": value}

    word = _plural_ru(count, "событие", "события", "событий")
    return {
        "state": f"Сегодня {count} {word}.",
        "text": f"Сегодня {count} {word}:\n{out}",
    }


def _format_due(due_raw: str | None) -> str:
    if not due_raw:
        return "Задача без даты."

    parsed = dt_util.parse_datetime(due_raw)
    if parsed is None:
        return "Задача без даты."

    due = parsed.date()
    if due.year != dt_util.now().year:
        return f"{due:%d} {_MONTHS_RU[due.month - 1]} {due.year}г."
    return f"{due:%d} {_MONTHS_RU[due.month - 1]}."


def list_task_lists(hass: HomeAssistant, token_file: str) -> list[dict[str, str]]:
    """Return all Google Task Lists available to the authorized account."""
    service = get_tasks_service(hass, token_file)
    task_lists: list[dict[str, str]] = []
    page_token: str | None = None

    while True:
        result = (
            service.tasklists()
            .list(maxResults=100, pageToken=page_token)
            .execute()
        )
        for item in result.get("items", []):
            task_list_id = item.get("id")
            if not task_list_id:
                continue
            task_lists.append(
                {
                    "id": task_list_id,
                    "title": item.get("title") or "Без названия",
                }
            )

        page_token = result.get("nextPageToken")
        if not page_token:
            break

    return task_lists


def fetch_tasks(
    hass: HomeAssistant,
    token_file: str,
    task_list_id: str | None = None,
) -> dict[str, str]:
    """Return tasks in the same format as the legacy google_tasks.py script."""
    service = get_tasks_service(hass, token_file)

    if not task_list_id:
        # Compatibility fallback for installations upgraded from v1.1.0:
        # until the user chooses a Task List in Options, use the same list
        # as the legacy script (the last list returned by Google).
        task_lists = list_task_lists(hass, token_file)
        if not task_lists:
            return {
                "state": "Задач не найдено.",
                "text": "Задач не найдено.",
                "notes": "Задач не найдено.",
            }
        task_list_id = task_lists[-1]["id"]

    tasks_result = service.tasks().list(tasklist=task_list_id, maxResults=50).execute()
    tasks = tasks_result.get("items", [])

    if not tasks:
        return {
            "state": "Задач не найдено.",
            "text": "Задач не найдено.",
            "notes": "Задач не найдено.",
        }

    out_lines: list[str] = []
    note_blocks: list[str] = []

    for idx, task in enumerate(tasks, start=1):
        due = _format_due(task.get("due"))
        title = task.get("title") or "Задача без заголовка"
        notes = task.get("notes") or "Задача без описания."

        line = _append_period_if_needed(f"{idx}. {due} {title}")
        out_lines.append(line)

        title_for_notes = _append_period_if_needed(title)
        note_blocks.append(
            f"Описание задачи {idx}: {title_for_notes}\n"
            f"Срок выполнения: {due}\n"
            f"{notes}\n"
        )

    count = len(tasks)
    word = _plural_ru(count, "задача", "задачи", "задач")
    prefix = "Запланирована " if count % 10 == 1 and count % 100 != 11 else "Запланировано "

    if count == 1:
        count_text: str | int = "одна"
    elif count == 2:
        count_text = "две"
    else:
        count_text = count

    return {
        "state": f"{prefix}{count} {word}.\n",
        "text": f"{prefix}{count_text} {word}:\n" + "\n".join(out_lines) + "\n",
        "notes": "\n".join(note_blocks),
    }
