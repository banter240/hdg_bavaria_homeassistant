"""Accessor for the per-entry data this integration stores in hass.data."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, cast

from ..const import DOMAIN

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant

__all__ = ["get_integration_data"]


def get_integration_data(hass: HomeAssistant, entry_id: str) -> dict[str, Any]:
    """Return hass.data[DOMAIN][entry_id]; raises KeyError when missing."""
    return cast(dict[str, Any], hass.data[DOMAIN][entry_id])
