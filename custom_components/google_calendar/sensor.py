from __future__ import annotations

from dataclasses import dataclass
from functools import partial
from typing import Any, Callable

from homeassistant.components.sensor import SensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .api import (
    fetch_contacts_birthdays,
    fetch_events,
    fetch_holidays,
    fetch_tasks,
)
from .const import (
    CONF_CALENDAR_ID,
    CONF_TOKEN_FILE,
    CONF_TASK_LIST_ID,
    DEFAULT_CALENDAR_ID,
    UPDATE_INTERVAL_CONTACTS,
    UPDATE_INTERVAL_EVENTS,
    UPDATE_INTERVAL_HOLIDAYS,
    UPDATE_INTERVAL_TASKS,
)
from .coordinator import GoogleDataCoordinator

PARALLEL_UPDATES = 0


@dataclass(frozen=True, slots=True)
class GoogleSensorDescription:
    name: str
    unique_id: str
    entity_id: str
    interval: Any
    fetcher: str


SENSORS = (
    GoogleSensorDescription(
        name="Google Calendar Events",
        unique_id="google_calendar_events",
        entity_id="sensor.google_calendar_events",
        interval=UPDATE_INTERVAL_EVENTS,
        fetcher="events",
    ),
    GoogleSensorDescription(
        name="Google Calendar Holidays",
        unique_id="google_calendar_holidays",
        entity_id="sensor.google_calendar_holidays",
        interval=UPDATE_INTERVAL_HOLIDAYS,
        fetcher="holidays",
    ),
    GoogleSensorDescription(
        name="Google Calendar Contacts Birthdays",
        unique_id="google_calendar_contacts_birthdays",
        entity_id="sensor.google_calendar_contacts_birthdays",
        interval=UPDATE_INTERVAL_CONTACTS,
        fetcher="contacts",
    ),
    GoogleSensorDescription(
        name="Google Tasks",
        unique_id="google_tasks",
        entity_id="sensor.google_tasks",
        interval=UPDATE_INTERVAL_TASKS,
        fetcher="tasks",
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    token_file = entry.data[CONF_TOKEN_FILE]
    calendar_id = entry.data.get(CONF_CALENDAR_ID, DEFAULT_CALENDAR_ID)
    task_list_id = entry.options.get(CONF_TASK_LIST_ID)

    fetchers: dict[str, Callable[[], dict[str, Any]]] = {
        "events": partial(fetch_events, hass, token_file, calendar_id),
        "holidays": partial(fetch_holidays, hass, token_file),
        "contacts": partial(fetch_contacts_birthdays, hass, token_file),
        "tasks": partial(fetch_tasks, hass, token_file, task_list_id),
    }

    entities: list[GoogleCalendarSensor] = []

    # Refresh each source independently. A failure in Tasks, for example due to
    # missing OAuth scope before re-authorization, must not prevent the three
    # Calendar sensors from loading.
    for description in SENSORS:
        coordinator = GoogleDataCoordinator(
            hass,
            entry,
            description.unique_id,
            description.interval,
            fetchers[description.fetcher],
        )
        await coordinator.async_refresh()
        entities.append(GoogleCalendarSensor(coordinator, description))

    async_add_entities(entities)


class GoogleCalendarSensor(CoordinatorEntity[GoogleDataCoordinator], SensorEntity):
    _attr_icon = "mdi:calendar-text"

    def __init__(
        self,
        coordinator: GoogleDataCoordinator,
        description: GoogleSensorDescription,
    ) -> None:
        super().__init__(coordinator)
        self._description = description
        self._attr_name = description.name
        self._attr_unique_id = description.unique_id
        # This preserves the entity_ids used by the legacy command_line sensors
        # as long as those entity_ids are free in the entity registry.
        self.entity_id = description.entity_id

    @property
    def native_value(self) -> str | None:
        if not self.coordinator.data:
            return None
        return self.coordinator.data.get("state")

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        if not self.coordinator.data:
            return {}
        return {
            key: value
            for key, value in self.coordinator.data.items()
            if key != "state"
        }
