"""Provides diagnostic support for the HDG Bavaria Boiler integration."""

from __future__ import annotations

__all__ = ["async_get_config_entry_diagnostics"]

import ipaddress
from typing import Any, cast
from urllib.parse import ParseResult, urlparse, urlunparse

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er

from .const import (
    CONF_HOST_IP,
    DIAGNOSTICS_REDACTED_PLACEHOLDER,
    DIAGNOSTICS_SENSITIVE_COORDINATOR_DATA_NODE_IDS,
    DIAGNOSTICS_TO_REDACT_CONFIG_KEYS,
    DOMAIN,
)
from .coordinator import HdgDataUpdateCoordinator
from .helpers.logging_utils import (
    INTEGRATION_VERSION,
    get_redacted_logger,
    note_host_secret,
    note_log_secret,
    redact,
)
from .helpers.string_utils import normalize_unique_id_component

_LOGGER = get_redacted_logger(DOMAIN)


def _note_diagnostics_secrets(
    host_ip: str | None, coordinator: HdgDataUpdateCoordinator | None
) -> None:
    """Register host, serial, and MAC before any diagnostics text is built."""
    note_host_secret(host_ip)
    if coordinator is None:
        return
    note_host_secret(getattr(coordinator, "_hostname", None))
    data = coordinator.data
    if not isinstance(data, dict):
        return
    for node_id in DIAGNOSTICS_SENSITIVE_COORDINATOR_DATA_NODE_IDS:
        note_log_secret(data.get(node_id))


def _redact_diagnostics_value(value: Any) -> Any:
    """Run string redaction over a diagnostics structure."""
    if isinstance(value, str):
        return redact(value)
    if isinstance(value, dict):
        return {key: _redact_diagnostics_value(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_redact_diagnostics_value(item) for item in value]
    if isinstance(value, tuple):
        return tuple(_redact_diagnostics_value(item) for item in value)
    return value


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
            "integration_version": INTEGRATION_VERSION,
            "error": "Integration data not found. Setup might have failed.",
            "entry_id": entry.entry_id,
        }

    coordinator = integration_data.get("coordinator")
    api_client = integration_data.get("api_client")
    sensitive_host_ip = entry.data.get(CONF_HOST_IP)
    _note_diagnostics_secrets(sensitive_host_ip, coordinator)

    payload = {
        "integration_version": INTEGRATION_VERSION,
        "config_entry": _get_redacted_config_entry_info(entry, sensitive_host_ip),
        "coordinator": _get_coordinator_diagnostics(coordinator),
        "api_client": _get_api_client_diagnostics(api_client, sensitive_host_ip),
        "entities": await _get_entity_diagnostics(hass, entry, sensitive_host_ip),
    }
    return cast(dict[str, Any], _redact_diagnostics_value(payload))


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

    coordinator_state = coordinator.get_diagnostics()
    if coordinator_state.get("hostname"):
        coordinator_state["hostname"] = DIAGNOSTICS_REDACTED_PLACEHOLDER

    coordinator_diag: dict[str, Any] = {
        "last_update_success": coordinator.last_update_success,
        "scan_intervals_used": {
            k: v.total_seconds() for k, v in coordinator.scan_intervals.items()
        },
        **coordinator_state,
    }
    if coordinator.data:
        coordinator_diag["data_item_count"] = len(coordinator.data)
        coordinator_diag["data"] = async_redact_data(
            coordinator.data, DIAGNOSTICS_SENSITIVE_COORDINATOR_DATA_NODE_IDS
        )

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
        _LOGGER.debug("Redacted a sensitive component in a unique_id.")
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
        # The API path and query are routes, not secrets. The host is.
        return cast(
            str,
            urlunparse(
                parsed._replace(
                    netloc=redacted_netloc,
                    params="",
                    fragment="",
                )
            ),
        )
    except Exception as e:
        _LOGGER.warning("Error redacting API base URL: %s", e)
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
