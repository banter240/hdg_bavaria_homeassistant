"""Button that polls every HDG node group immediately."""

from __future__ import annotations

__all__ = ["async_setup_entry"]

import logging

from homeassistant.components.button import ButtonEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN, USER_ACTION_LOGGER_NAME
from .coordinator import HdgDataUpdateCoordinator
from .entity import HdgBaseEntity

_USER_ACTION_LOGGER = logging.getLogger(USER_ACTION_LOGGER_NAME)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the poll-everything button."""
    coordinator: HdgDataUpdateCoordinator = hass.data[DOMAIN][entry.entry_id][
        "coordinator"
    ]
    async_add_entities([HdgPollEverythingButton(coordinator)])


class HdgPollEverythingButton(HdgBaseEntity, ButtonEntity):
    """Poll every node group immediately."""

    _attr_translation_key = "poll_everything"
    _attr_icon = "mdi:refresh"

    def __init__(self, coordinator: HdgDataUpdateCoordinator) -> None:
        """Initialize the button."""
        super().__init__(coordinator, "poll_everything")

    async def async_press(self) -> None:
        """Poll every node group."""
        _USER_ACTION_LOGGER.info("User requested a full poll.")
        if not await self.coordinator.async_poll_everything():
            raise HomeAssistantError("Full poll failed")
