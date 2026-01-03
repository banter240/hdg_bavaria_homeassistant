"""Provides diagnostic support for the HDG Bavaria Boiler integration."""

from __future__ import annotations

__version__ = "0.2.2"
__all__ = ["async_get_config_entry_diagnostics"]

import ipaddress
import logging
from typing import Any, cast
from urllib.parse import ParseResult, urlparse, urlunparse

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
from homeassistant.util import dt as dt_util

from .const import (
    CONF_HOST_IP,
    DIAGNOSTICS_REDACTED_PLACEHOLDER,
    DIAGNOSTICS_SENSITIVE_COORDINATOR_DATA_NODE_IDS,
    DIAGNOSTICS_TO_REDACT_CONFIG_KEYS,
    DOMAIN,
)
from .coordinator import HdgDataUpdateCoordinator
from .helpers.logging_utils import format_for_log
from .helpers.string_utils import normalize_unique_id_component

_LOGGER = logging.getLogger(DOMAIN)


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: ConfigEntry
) -> dict[str, Any]:
    """Generate and return diagnostics for a given config entry."""
    integration_data = hass.data.get(DOMAIN, {}).get(entry.entry_id)
    if not integration_data:
        _LOGGER.warning(
            "Integration data for entry %s not found. Diagnostics will be limited.",
            entry.entry_id,
        )
        return {
            "error": "Integration data not found. Setup might have failed.",
            "entry_id": entry.entry_id,
        }

    coordinator = integration_data.get("coordinator")
    api_client = integration_data.get("api_client")
    sensitive_host_ip = entry.data.get(CONF_HOST_IP)

    return {
        "config_entry": _get_redacted_config_entry_info(entry, sensitive_host_ip),
        "coordinator": _get_coordinator_diagnostics(coordinator),
        "api_client": _get_api_client_diagnostics(api_client, sensitive_host_ip),
        "entities": await _get_entity_diagnostics(hass, entry, sensitive_host_ip),
    }


def _get_redacted_config_entry_info(
    entry: ConfigEntry, sensitive_host_ip: str | None
) -> dict[str, Any]:
    """Return redacted configuration entry information."""
    return {
        "title": entry.title,
        "entry_id": entry.entry_id,
        "data": async_redact_data(entry.data, DIAGNOSTICS_TO_REDACT_CONFIG_KEYS),
        "options": async_redact_data(entry.options, DIAGNOSTICS_TO_REDACT_CONFIG_KEYS),
        "unique_id": _get_redacted_unique_id(
            entry.unique_id, sensitive_host_ip, DIAGNOSTICS_REDACTED_PLACEHOLDER
        ),
    }


def _get_coordinator_diagnostics(
    coordinator: HdgDataUpdateCoordinator | None,
) -> dict[str, Any] | str:
    """Return diagnostic information about the DataUpdateCoordinator."""
    if not coordinator:
        return "Coordinator not found or not initialized."

    # Access internal polling state if available
    polling_state = getattr(coordinator, "_polling_state", {})

    # Try to find last update success time (not standard in DataUpdateCoordinator)
    last_update_success_time = getattr(coordinator, "last_update_success_time", None)

    coordinator_diag: dict[str, Any] = {
        "last_update_success": coordinator.last_update_success,
        "last_update_time_successful": (
            last_update_success_time.isoformat() if last_update_success_time else None
        ),
        "scan_intervals_used": {
            k: v.total_seconds() for k, v in coordinator.scan_intervals.items()
        },
        "last_update_times_per_group": {
            k: dt_util.utc_from_timestamp(v).isoformat()
            for k, v in coordinator.last_update_times_public.items()
        },
        "consecutive_poll_failures": polling_state.get("consecutive_failures"),
        "boiler_considered_online": coordinator.boiler_is_online,
        "failed_poll_group_retry_info": {
            k: {
                "attempts": v["attempts"],
                "next_retry_time_utc": dt_util.utc_from_timestamp(
                    v["next_retry_time"]
                ).isoformat(),
            }
            for k, v in polling_state.get("failed_group_retry_info", {}).items()
            if v["next_retry_time"] > 0
        },
    }
    if coordinator.data:
        redacted_data = async_redact_data(
            coordinator.data, DIAGNOSTICS_SENSITIVE_COORDINATOR_DATA_NODE_IDS
        )
        coordinator_diag["data_item_count"] = len(redacted_data)
        coordinator_diag["data_sample_keys"] = list(redacted_data.keys())[:20]

    return coordinator_diag


def _get_api_client_diagnostics(
    api_client: Any, sensitive_host_ip: str | None
) -> dict[str, Any]:
    """Return diagnostic information about the HdgApiClient."""
    if not api_client:
        return {"error": "API Client not found or not initialized."}
    return {"base_url": _redact_api_client_base_url(api_client, sensitive_host_ip)}


async def _get_entity_diagnostics(
    hass: HomeAssistant, entry: ConfigEntry, sensitive_host_ip: str | None
) -> list[dict[str, Any]]:
    """Return information about entities associated with this config entry."""
    entity_reg = er.async_get(hass)
    entities = er.async_entries_for_config_entry(entity_reg, entry.entry_id)

    return [
        {
            "entity_id": entity.entity_id,
            "unique_id": _get_redacted_unique_id(
                entity.unique_id,
                sensitive_host_ip,
                DIAGNOSTICS_REDACTED_PLACEHOLDER,
            ),
            "platform": entity.platform,
            "disabled_by": entity.disabled_by,
        }
        for entity in entities
    ]


def _get_redacted_unique_id(
    unique_id: str | None, sensitive_raw_value: str | None, placeholder: str
) -> str:
    """Redact a sensitive raw value from a unique_id string."""
    if not unique_id or not sensitive_raw_value:
        return unique_id or ""

    norm_sensitive = normalize_unique_id_component(sensitive_raw_value)
    if norm_sensitive in normalize_unique_id_component(unique_id):
        _LOGGER.debug(
            "Redacting sensitive component '%s' in unique_id '%s'.",
            format_for_log(sensitive_raw_value),
            format_for_log(unique_id),
        )
        return unique_id.replace(norm_sensitive, placeholder)
    return unique_id


def _redact_api_client_base_url(api_client: Any, sensitive_host_ip: str | None) -> str:
    """Redact sensitive parts from the API client's base URL."""
    base_url = getattr(api_client, "base_url", None)
    if not base_url:
        return "Unknown"

    try:
        parsed = urlparse(base_url)
        redacted_netloc = _build_redacted_netloc(parsed, sensitive_host_ip)
        redacted_path = (
            DIAGNOSTICS_REDACTED_PLACEHOLDER
            if parsed.path and parsed.path != "/"
            else parsed.path
        )
        return cast(
            str,
            urlunparse(
                parsed._replace(
                    netloc=redacted_netloc,
                    path=redacted_path,
                    query=DIAGNOSTICS_REDACTED_PLACEHOLDER if parsed.query else "",
                    params="",
                    fragment="",
                )
            ),
        )
    except Exception as e:
        _LOGGER.warning("Error redacting base_url '%s': %s", base_url, e)
        return DIAGNOSTICS_REDACTED_PLACEHOLDER


def _build_redacted_netloc(
    parsed_url: ParseResult, sensitive_host_ip: str | None
) -> str:
    """Build a redacted network location (netloc) string."""
    netloc_parts = []
    if parsed_url.username:
        netloc_parts.append(
            f"{DIAGNOSTICS_REDACTED_PLACEHOLDER}@{DIAGNOSTICS_REDACTED_PLACEHOLDER}"
        )

    if hostname := parsed_url.hostname:
        is_ip_address: bool
        try:
            ipaddress.ip_address(hostname)
            is_ip_address = True
        except ValueError:
            is_ip_address = False

        if (
            sensitive_host_ip and hostname.lower() == sensitive_host_ip.lower()
        ) or is_ip_address:
            netloc_parts.append(DIAGNOSTICS_REDACTED_PLACEHOLDER)
        else:
            netloc_parts.append(hostname)
    else:
        netloc_parts.append(DIAGNOSTICS_REDACTED_PLACEHOLDER)

    if parsed_url.port:
        netloc_parts.append(f":{parsed_url.port}")

    return "".join(netloc_parts)
