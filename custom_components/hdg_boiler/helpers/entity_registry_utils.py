"""Entity registry utilities."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.entity_registry import RegistryEntryDisabler

from .logging_utils import get_redacted_logger

if TYPE_CHECKING:
    from homeassistant.config_entries import ConfigEntry

_LOGGER = get_redacted_logger(__name__)

PLATFORM_SUFFIXES: tuple[str, ...] = ("_sensor", "_number", "_select")

__all__ = [
    "PLATFORM_SUFFIXES",
    "strip_platform_suffix",
    "async_sync_entities_by_key",
]


def strip_platform_suffix(unique_id: str) -> str | None:
    """Return the definition key encoded in a unique_id, or None.

    unique_id shape: "{domain}::{device}::{key}_{platform}". Strips one
    known platform suffix; unknown shapes yield None.
    """
    parts = unique_id.split("::")
    if len(parts) != 3:
        return None
    suffix = parts[2]
    return next(
        (
            suffix[: -len(plat_sfx)]
            for plat_sfx in PLATFORM_SUFFIXES
            if suffix.endswith(plat_sfx)
        ),
        suffix,
    )


async def async_sync_entities_by_key(
    hass: HomeAssistant,
    entry: ConfigEntry,
    key_to_should_enable: dict[str, bool],
    *,
    disabler: RegistryEntryDisabler = RegistryEntryDisabler.INTEGRATION,
    log_prefix: str = "entity",
    logger: logging.Logger | None = None,
    key_to_log_name: dict[str, str] | None = None,
    enabled_msg: str = (
        "Enabled {log_prefix} {entity_id} (group '{name}' toggled on)."
    ),
    disabled_msg: str = (
        "Disabled {log_prefix} {entity_id} (group '{name}' toggled off)."
    ),
) -> None:
    """Enable/disable entities based on key -> should_enable mapping.

    Strips platform suffixes from unique_id and toggles RegistryEntryDisabler.
    The enabled_msg/disabled_msg templates receive log_prefix, entity_id,
    and name (the display name for the key).
    """
    if not key_to_should_enable:
        return

    log = logger or _LOGGER
    ent_reg = er.async_get(hass)
    for reg_entry in er.async_entries_for_config_entry(ent_reg, entry.entry_id):
        suffix = strip_platform_suffix(reg_entry.unique_id)
        if suffix is None or suffix not in key_to_should_enable:
            continue

        should_be_enabled = key_to_should_enable[suffix]
        log_name = key_to_log_name.get(suffix, suffix) if key_to_log_name else suffix
        msg_tpl = enabled_msg if should_be_enabled else disabled_msg

        if should_be_enabled and reg_entry.disabled_by == disabler:
            ent_reg.async_update_entity(reg_entry.entity_id, disabled_by=None)
            log.debug(
                msg_tpl.format(
                    log_prefix=log_prefix,
                    entity_id=reg_entry.entity_id,
                    name=log_name,
                )
            )
        elif not should_be_enabled and reg_entry.disabled_by is None:
            ent_reg.async_update_entity(
                reg_entry.entity_id,
                disabled_by=disabler,
            )
            log.debug(
                msg_tpl.format(
                    log_prefix=log_prefix,
                    entity_id=reg_entry.entity_id,
                    name=log_name,
                )
            )
