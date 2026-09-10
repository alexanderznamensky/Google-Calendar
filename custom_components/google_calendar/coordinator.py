from __future__ import annotations

import logging
from collections.abc import Callable
from datetime import timedelta
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

_LOGGER = logging.getLogger(__name__)


class GoogleDataCoordinator(DataUpdateCoordinator[dict[str, Any]]):
    """Coordinator for one Google Calendar/Tasks sensor."""

    def __init__(
        self,
        hass: HomeAssistant,
        entry: ConfigEntry,
        name: str,
        update_interval: timedelta,
        update_method: Callable[[], dict[str, Any]],
    ) -> None:
        super().__init__(
            hass,
            _LOGGER,
            name=name,
            config_entry=entry,
            update_interval=update_interval,
        )
        self._sync_update_method = update_method

    async def _async_update_data(self) -> dict[str, Any]:
        try:
            return await self.hass.async_add_executor_job(self._sync_update_method)
        except Exception as err:
            raise UpdateFailed(str(err)) from err
