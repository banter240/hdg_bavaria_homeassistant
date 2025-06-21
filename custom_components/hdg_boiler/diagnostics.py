"""Provides diagnostic support for the HDG Bavaria Boiler integration.

This module includes functions to gather comprehensive diagnostic information,
such as configuration details, coordinator status, API client information,
and entity states. This data aids in troubleshooting and support for the integration.
"""

from __future__ import annotations

__version__ = "0.9.36"
import ipaddress
import logging
from typing import Any, cast
from urllib.parse import ParseResult, urlparse, urlunparse

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
from homeassistant.util import dt as dt_util

from .api import HdgApiClient
from .const import (
    CONF_HOST_IP,
    DIAGNOSTICS_REDACTED_PLACEHOLDER,
    DIAGNOSTICS_SENSITIVE_COORDINATOR_DATA_NODE_IDS,
    DIAGNOSTICS_TO_REDACT_CONFIG_KEYS,
    DOMAIN,
)
from .coordinator import HdgDataUpdateCoordinator
from .helpers.string_utils import normalize_unique_id_component

_LOGGER = logging.getLogger(DOMAIN)


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: ConfigEntry
) -> dict[str, Any]:
    """Asynchronously generate and return diagnostics data for a config entry.

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
    diag_data: dict[str, Any] = {
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


def _get_redacted_unique_id(
    unique_id: str | None,
    sensitive_raw_value: str | None,
    placeholder: str,
) -> str:
    """Redacts a sensitive raw value (like host_ip) from a unique_id string for diagnostics output.

    Unique IDs can sometimes contain sensitive information derived from the configuration,
    such as the host IP. This function replaces occurrences of the sensitive raw value
    (after normalization for comparison) within the unique ID string with a placeholder.

    Args:
        unique_id: The original unique ID string.
        sensitive_raw_value: The specific sensitive value (e.g., host IP) to look for and redact.
                             This value is normalized using `normalize_unique_id_component`
                             before being compared against parts of the unique ID.
        placeholder: The string to use as a replacement for the sensitive value.

    Returns:
        The unique ID string with sensitive parts replaced by the placeholder.

    """
    if not unique_id or not sensitive_raw_value:
        return unique_id or ""

    normalized_sensitive_component = normalize_unique_id_component(sensitive_raw_value)

    # Case 1: The entire unique_id (when normalized) matches the sensitive component.
    # This is common for the config entry's own unique_id if it's just the host_ip.
    if normalize_unique_id_component(unique_id) == normalized_sensitive_component:
        _LOGGER.debug(
            f"Redacting full unique_id '{unique_id}' as it matches sensitive value '{sensitive_raw_value}'."
        )
        return placeholder

    # Case 2: The sensitive component is a distinct part, typically delimited by "::".
    # Assumes unique_id parts are already normalized if they represent the host.
    parts = unique_id.split("::")
    redacted_parts = []
    was_redacted_in_parts = False
    for part in parts:
        if part == normalized_sensitive_component:
            redacted_parts.append(placeholder)
            was_redacted_in_parts = True
        else:
            redacted_parts.append(part)

    if was_redacted_in_parts:
        _LOGGER.debug(
            f"Redacted sensitive component '{sensitive_raw_value}' (normalized: '{normalized_sensitive_component}') "
            f"within unique_id '{unique_id}' using part-based matching."
        )
        return "::".join(redacted_parts)

    # Fallback: If the normalized sensitive component is found as a substring.
    # This is broader and used if specific structural matches above didn't apply.
    # This helps catch cases where the sensitive value might be embedded differently.
    if normalized_sensitive_component in unique_id:
        _LOGGER.debug(
            f"Performing fallback redaction of '{sensitive_raw_value}' (normalized: '{normalized_sensitive_component}') "
            f"in unique_id '{unique_id}' as it was found as a substring."
        )
        return unique_id.replace(normalized_sensitive_component, placeholder)

    return unique_id


def _get_redacted_config_entry_info(entry: ConfigEntry) -> dict[str, Any]:
    """Prepare redacted configuration entry information for diagnostics.

    Args:
        entry: The ConfigEntry object.

    Returns:
        A dictionary containing redacted configuration entry information.

    """
    sensitive_host_ip = entry.data.get(CONF_HOST_IP)

    unique_id_display = _get_redacted_unique_id(
        entry.unique_id,
        sensitive_host_ip,
        DIAGNOSTICS_REDACTED_PLACEHOLDER,
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
) -> dict[str, Any] | str:
    """Gather diagnostic information about the DataUpdateCoordinator.

    Args:
        coordinator: The HdgDataUpdateCoordinator instance. Can be None if not initialized.

    Returns:
        A dictionary with coordinator diagnostics, or a string message if the
        coordinator is not found or not initialized.

    """
    if coordinator:
        coordinator_diag: dict[str, Any] = {  # type: ignore[attr-defined]
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
                for group_key, timestamp in coordinator.last_update_times_public.items()
                if isinstance(timestamp, int | float)
            },
        }
        if coordinator.data:
            redacted_coordinator_data = async_redact_data(
                coordinator.data, DIAGNOSTICS_SENSITIVE_COORDINATOR_DATA_NODE_IDS
            )
            coordinator_diag["data_sample_keys"] = list(
                redacted_coordinator_data.keys()
            )[:20]
            coordinator_diag["data_item_count"] = len(redacted_coordinator_data)
        return coordinator_diag
    return "Coordinator not found or not initialized."


def _is_ip_address_for_redaction(host_to_check: str) -> bool:
    """Check if a host string is an IP address."""
    try:
        ipaddress.ip_address(host_to_check)
        return True
    except ValueError:
        return False


def _build_redacted_netloc(
    parsed_url: ParseResult, sensitive_host_ip: str | None
) -> str:
    """Build the redacted network location (netloc) string.

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
        netloc_parts.append(
            DIAGNOSTICS_REDACTED_PLACEHOLDER  # This case implies an invalid or unexpected URL structure.
        )
    if parsed_url.port:
        netloc_parts.append(f":{parsed_url.port}")
    return "".join(netloc_parts)


def _redact_api_client_base_url(
    api_client: HdgApiClient, sensitive_host_ip: str | None
) -> str:
    """Redact sensitive parts (host IP or general IP addresses) from the API client's base URL.

    Args:
        api_client: The HdgApiClient instance.
        sensitive_host_ip: The specific host IP or hostname to redact, if known.

    Returns:
        The redacted base URL string, or "Unknown" if the base URL cannot be determined.

    """
    if not (base_url := getattr(api_client, "base_url", None)):
        return "Unknown"

    try:
        parsed = urlparse(base_url)
        redacted_netloc = _build_redacted_netloc(parsed, sensitive_host_ip)

        # Redact path and query as they might contain sensitive info, though less common for base URLs.
        redacted_path = (
            DIAGNOSTICS_REDACTED_PLACEHOLDER
            if parsed.path and parsed.path != "/"
            else parsed.path
        )
        redacted_query = DIAGNOSTICS_REDACTED_PLACEHOLDER if parsed.query else ""

        # Correctly cast the result of urlunparse to str
        return cast(
            str,
            urlunparse(
                parsed._replace(
                    netloc=redacted_netloc,
                    path=redacted_path,
                    query=redacted_query,
                    params="",  # Parameters are typically not part of a base URL.
                    fragment="",  # Fragments are typically not part of a base URL.
                )
            ),
        )
    except Exception as e:
        _LOGGER.warning(f"Error redacting API client base_url '{base_url}': {e}")
        # Ensure the fallback return is also cast to str
        return cast(str, DIAGNOSTICS_REDACTED_PLACEHOLDER)


def _get_api_client_diagnostics(
    api_client: HdgApiClient | None, sensitive_host_ip: str | None
) -> dict[str, Any]:
    """Gather diagnostic information about the HdgApiClient.

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


async def _get_entity_diagnostics(
    hass: HomeAssistant, entry: ConfigEntry
) -> list[dict[str, Any]]:
    """Retrieve information about entities associated with this config entry.

    Args:
        hass: The Home Assistant instance.
        entry: The config entry whose entities are to be listed.

    Returns:
        A list of dictionaries, where each dictionary represents an entity
        and contains its diagnostic information.

    """
    entity_registry = er.async_get(hass)
    entities = er.async_entries_for_config_entry(entity_registry, entry.entry_id)

    diagnostics_entities = []
    sensitive_host_ip_for_redaction = entry.data.get(CONF_HOST_IP)

    for entity in entities:
        unique_id_display = _get_redacted_unique_id(
            entity.unique_id,
            sensitive_host_ip_for_redaction,
            DIAGNOSTICS_REDACTED_PLACEHOLDER,
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
