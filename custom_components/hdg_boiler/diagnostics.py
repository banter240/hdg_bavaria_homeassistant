"""
Diagnostics support for the HDG Bavaria Boiler integration.

This module provides functions to gather diagnostic information for the
HDG Bavaria Boiler integration, aiding in troubleshooting and support by
collecting configuration details, coordinator status, API client information,
and entity states.
"""

from __future__ import annotations

__version__ = "0.9.32"

import logging
from typing import Any, Dict

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.components.diagnostics import async_redact_data
from homeassistant.util import dt as dt_util

import ipaddress
from urllib.parse import urlparse, urlunparse
from homeassistant.helpers import entity_registry as er
from .utils import normalize_unique_id_component
from .const import (
    DOMAIN,
    CONF_HOST_IP,
    DIAGNOSTICS_TO_REDACT_CONFIG_KEYS,
    DIAGNOSTICS_SENSITIVE_COORDINATOR_DATA_NODE_IDS,
    DIAGNOSTICS_REDACTED_PLACEHOLDER,
)
from .coordinator import HdgDataUpdateCoordinator
from .api import HdgApiClient

_LOGGER = logging.getLogger(DOMAIN)


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: ConfigEntry
) -> Dict[str, Any]:
    """
    Asynchronously generate and return diagnostics data for a config entry.

    Args:
        hass: The Home Assistant instance.
        entry: The config entry for which to gather diagnostics.

    Returns:
        A dictionary containing the diagnostics data. If essential integration
        data is missing, an error dictionary is returned instead.
    """
    integration_data = hass.data.get(DOMAIN, {}).get(entry.entry_id)
    if not integration_data:
        _LOGGER.warning(
            f"Integration data for entry {entry.entry_id} not found. Diagnostics will be limited."
        )
        return {
            "error": {
                "code": "integration_data_missing",
                "message": "Integration data not found. Setup might not have completed successfully.",
                "details": {"entry_id": entry.entry_id, "domain": DOMAIN},
            }
        }

    coordinator: HdgDataUpdateCoordinator = integration_data.get("coordinator")
    api_client: HdgApiClient = integration_data.get("api_client")
    diag_data: Dict[str, Any] = {
        "config_entry": _get_redacted_config_entry_info(entry),
        "coordinator": (
            _get_coordinator_diagnostics(coordinator)
            if coordinator is not None
            else "Coordinator not found or not initialized."
        ),
        "api_client": (
            _get_api_client_diagnostics(api_client, entry.data.get(CONF_HOST_IP))
            if api_client is not None
            else {"error": "API Client not found or not initialized."}
        ),
        "entities": await _get_entity_diagnostics(hass, entry),
    }

    return diag_data


def _get_redacted_config_entry_info(entry: ConfigEntry) -> Dict[str, Any]:
    """
    Prepare redacted configuration entry information for diagnostics.

    Args:
        entry: The ConfigEntry object.

    Returns:
        A dictionary containing redacted configuration entry information.
    """
    sensitive_host_ip = entry.data.get(CONF_HOST_IP)

    # Redact sensitive_host_ip from unique_id if it's used as the device identifier part.
    # The unique_id format is typically DOMAIN::DEVICE_IDENTIFIER::SUFFIX
    # DEVICE_IDENTIFIER can be host_ip (normalized) or device_alias.
    unique_id_display = entry.unique_id or ""  # Ensure unique_id_display is a string
    if sensitive_host_ip and entry.unique_id:  # entry.unique_id is often the host_ip itself
        normalized_sensitive_host_for_id = normalize_unique_id_component(sensitive_host_ip)

        # Attempt to match the normalized host IP as a whole component within the unique ID.
        # This pattern looks for the normalized host IP either surrounded by '::' or at the start/end.
        # Example unique_id: "hdg_boiler::normalized_host_ip::entity_suffix"
        # Example unique_id: "hdg_boiler::device_alias::entity_suffix" (where device_alias might contain host_ip)
        # If entry.unique_id itself is the host_ip (common case for config entry unique_id):
        if normalize_unique_id_component(entry.unique_id) == normalized_sensitive_host_for_id:
            unique_id_display = DIAGNOSTICS_REDACTED_PLACEHOLDER
            _LOGGER.debug(
                f"Redacted unique_id as it matches sensitive host IP for entry {entry.entry_id}."
            )
        elif f"::{normalized_sensitive_host_for_id}::" in unique_id_display:
            unique_id_display = unique_id_display.replace(
                f"::{normalized_sensitive_host_for_id}::",
                f"::{DIAGNOSTICS_REDACTED_PLACEHOLDER}::",
            )
            _LOGGER.debug(
                f"Redacted sensitive host IP component in unique_id for entry {entry.entry_id}."
            )

    return {
        "title": entry.title,
        "entry_id": entry.entry_id,
        "data": async_redact_data(entry.data, DIAGNOSTICS_TO_REDACT_CONFIG_KEYS),
        "options": async_redact_data(entry.options, DIAGNOSTICS_TO_REDACT_CONFIG_KEYS),
        "unique_id": unique_id_display,
    }


def _get_coordinator_diagnostics(
    coordinator: HdgDataUpdateCoordinator | None,
) -> Dict[str, Any] | str:
    """
    Gather diagnostic information about the DataUpdateCoordinator.

    Args:
        coordinator: The HdgDataUpdateCoordinator instance. Can be None if not initialized.

    Returns:
        A dictionary with coordinator diagnostics, or a string message if the
        coordinator is not found or not initialized.
    """
    if coordinator:
        coordinator_diag = {
            "last_update_success": coordinator.last_update_success,
            "last_update_time_successful": (
                coordinator.last_update_success_time.isoformat()
                if coordinator.last_update_success_time
                else None
            ),
            "data_sample_keys": [],
            "data_item_count": 0,
            "scan_intervals_used": {
                str(k): v.total_seconds() for k, v in coordinator.scan_intervals.items()
            },
            "last_update_times": {
                group_key: dt_util.utc_from_timestamp(timestamp).isoformat()
                for group_key, timestamp in coordinator.last_update_times.items()  # Use public property
                if isinstance(timestamp, (int, float))
            },
        }
        if coordinator.data:
            redacted_coordinator_data = async_redact_data(
                coordinator.data, DIAGNOSTICS_SENSITIVE_COORDINATOR_DATA_NODE_IDS
            )
            coordinator_diag["data_sample_keys"] = list(redacted_coordinator_data.keys())[:20]
            coordinator_diag["data_item_count"] = len(redacted_coordinator_data)
        return coordinator_diag
    return "Coordinator not found or not initialized."


def _is_ip_address_for_redaction(host_to_check: str) -> bool:
    """Helper to check if a host string is an IP address."""
    try:
        ipaddress.ip_address(host_to_check)
        return True
    except ValueError:
        return False


def _build_redacted_netloc(parsed_url: urlparse.ParseResult, sensitive_host_ip: str | None) -> str:
    """
    Build the redacted network location (netloc) string.

    Handles redaction of userinfo (username:password), host/IP, and port.

    Args:
        parsed_url: The ParseResult object from urlparse.
        sensitive_host_ip: The specific host IP or hostname to redact.

    Returns:
        The redacted netloc string.
    """
    netloc_parts = []
    # Redact userinfo (username:password@)
    if parsed_url.username:
        netloc_parts.append(DIAGNOSTICS_REDACTED_PLACEHOLDER)
        if parsed_url.password:
            netloc_parts.append(f":{DIAGNOSTICS_REDACTED_PLACEHOLDER}")
        netloc_parts.append("@")

    # Redact host/IP
    if host_to_check := parsed_url.hostname:
        if (
            sensitive_host_ip and host_to_check.lower() == sensitive_host_ip.lower()
        ) or _is_ip_address_for_redaction(host_to_check):
            netloc_parts.append(DIAGNOSTICS_REDACTED_PLACEHOLDER)
        else:
            netloc_parts.append(host_to_check)
    else:
        netloc_parts.append(DIAGNOSTICS_REDACTED_PLACEHOLDER)
    if parsed_url.port:
        netloc_parts.append(f":{parsed_url.port}")
    return "".join(netloc_parts)


def _redact_api_client_base_url(api_client: HdgApiClient, sensitive_host_ip: str | None) -> str:
    """
    Redact sensitive parts (host IP or general IP addresses) from the API client's base URL.

    Args:
        api_client: The HdgApiClient instance.
        sensitive_host_ip: The specific host IP or hostname to redact, if known.

    Returns:
        The redacted base URL string, or "Unknown" if the base URL cannot be determined.

    Note:
        This function assumes that `api_client` has a `base_url` attribute,
        which may be an empty string if the base URL is not set or invalid.
    """
    if not (base_url := getattr(api_client, "base_url", None)):
        return "Unknown"

    try:
        parsed = urlparse(base_url)
        redacted_netloc = _build_redacted_netloc(parsed, sensitive_host_ip)

        redacted_path = (
            DIAGNOSTICS_REDACTED_PLACEHOLDER if parsed.path and parsed.path != "/" else parsed.path
        )
        redacted_query = DIAGNOSTICS_REDACTED_PLACEHOLDER if parsed.query else ""

        return urlunparse(
            parsed._replace(
                netloc=redacted_netloc,
                path=redacted_path,
                query=redacted_query,
                params="",
                fragment="",
            )
        )
    except Exception as e:
        _LOGGER.warning(f"Error redacting API client base_url '{base_url}': {e}")
        return DIAGNOSTICS_REDACTED_PLACEHOLDER


def _get_api_client_diagnostics(
    api_client: HdgApiClient | None, sensitive_host_ip: str | None
) -> Dict[str, Any]:
    """
    Gather diagnostic information about the HdgApiClient.

    Args:
        api_client: The HdgApiClient instance. Can be None if not initialized.
        sensitive_host_ip: The specific host IP or hostname to redact from the base URL.
    Returns:
        A dictionary containing API client diagnostics (the redacted base URL),
        or an error message if the API client is not found.
    """
    if not api_client:
        return {"error": "API Client not found or not initialized."}
    base_url_display = _redact_api_client_base_url(api_client, sensitive_host_ip)
    return {"base_url": base_url_display}


async def _get_entity_diagnostics(hass: HomeAssistant, entry: ConfigEntry) -> list[Dict[str, Any]]:
    """
    Retrieve information about entities associated with this config entry.

    Args:
        hass: The Home Assistant instance.
        entry: The config entry whose entities are to be listed.

    Returns:
        A list of dictionaries, where each dictionary represents an entity
        and contains its diagnostic information.
    """
    entity_registry = er.async_get(hass)
    entities = await er.async_entries_for_config_entry(entity_registry, entry.entry_id)

    diagnostics_entities = []
    sensitive_host_ip_for_redaction = entry.data.get(CONF_HOST_IP)
    normalized_sensitive_host_for_id = (
        normalize_unique_id_component(sensitive_host_ip_for_redaction)
        if sensitive_host_ip_for_redaction
        else None
    )

    for entity in entities:
        unique_id_display = entity.unique_id
        if (
            normalized_sensitive_host_for_id
            and unique_id_display
            and normalized_sensitive_host_for_id in unique_id_display
        ):
            # Basic redaction: if the normalized host IP is part of the unique_id, replace it.
            # This is a simplified approach; more complex patterns might be needed for perfect redaction.
            unique_id_display = unique_id_display.replace(
                normalized_sensitive_host_for_id, DIAGNOSTICS_REDACTED_PLACEHOLDER
            )

        diagnostics_entities.append(
            {
                "entity_id": entity.entity_id,
                "unique_id": unique_id_display,
                "platform": entity.platform,
                "disabled_by": entity.disabled_by,
            }
        )
    return diagnostics_entities
