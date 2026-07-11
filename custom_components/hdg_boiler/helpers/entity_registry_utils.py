"""Entity registry utilities."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.entity_registry import RegistryEntryDisabler

if TYPE_CHECKING:
    from homeassistant.config_entries import ConfigEntry

_LOGGER = logging.getLogger(__name__)

PLATFORM_SUFFIXES: tuple[str, ...] = ("_sensor", "_number", "_select")


async def async_sync_entities_by_key(
    hass: HomeAssistant,
    entry: ConfigEntry,
    key_to_should_enable: dict[str, bool],
    *,
    disabler: RegistryEntryDisabler = RegistryEntryDisabler.INTEGRATION,
    log_prefix: str = "entity",
    logger: logging.Logger | None = None,
    key_to_log_name: dict[str, str] | None = None,
) -> None:
    """Enable/disable entities based on key -> should_enable mapping.

    Strips platform suffixes from unique_id and toggles RegistryEntryDisabler.
    """
    if not key_to_should_enable:
        return

    log = logger or _LOGGER
    ent_reg = er.async_get(hass)
    for reg_entry in er.async_entries_for_config_entry(ent_reg, entry.entry_id):
        parts = reg_entry.unique_id.split("::")
        if len(parts) != 3:
            continue

        suffix = parts[2]
        for plat_sfx in PLATFORM_SUFFIXES:
            if suffix.endswith(plat_sfx):
                suffix = suffix[: -len(plat_sfx)]
                break

        if suffix not in key_to_should_enable:
            continue

        should_be_enabled = key_to_should_enable[suffix]

        if log_prefix == "puffer sensor":
            if should_be_enabled and reg_entry.disabled_by == disabler:
                ent_reg.async_update_entity(reg_entry.entity_id, disabled_by=None)
                log.debug(
                    "Enabled puffer sensor %s (node ID configured).",
                    reg_entry.entity_id,
                )
            elif not should_be_enabled and reg_entry.disabled_by is None:
                ent_reg.async_update_entity(
                    reg_entry.entity_id,
                    disabled_by=disabler,
                )
                log.debug(
                    "Disabled puffer sensor %s (no node ID configured).",
                    reg_entry.entity_id,
                )
        else:
            log_name = suffix
            if key_to_log_name:
                log_name = key_to_log_name.get(suffix, suffix)

            if should_be_enabled and reg_entry.disabled_by == disabler:
                ent_reg.async_update_entity(reg_entry.entity_id, disabled_by=None)
                log.debug(
                    "Enabled %s %s (group '%s' toggled on).",
                    log_prefix,
                    reg_entry.entity_id,
                    log_name,
                )
            elif not should_be_enabled and reg_entry.disabled_by is None:
                ent_reg.async_update_entity(
                    reg_entry.entity_id,
                    disabled_by=disabler,
                )
                log.debug(
                    "Disabled %s %s (group '%s' toggled off).",
                    log_prefix,
                    reg_entry.entity_id,
                    log_name,
                )
