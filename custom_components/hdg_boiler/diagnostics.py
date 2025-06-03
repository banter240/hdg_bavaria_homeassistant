"""
Diagnostics support for the HDG Bavaria Boiler integration.

This module provides functions to gather diagnostic information for the
HDG Bavaria Boiler integration, aiding in troubleshooting and support by
collecting configuration details, coordinator status, API client information,
and entity states.
"""

from __future__ import annotations

__version__ = "0.9.30"

import logging
from typing import Any, Dict

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.components.diagnostics import async_redact_data
from homeassistant.util import dt as dt_util
import re
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
    base_url_value = getattr(api_client, "base_url", None)
    if not base_url_value:  # Handles None from getattr or if base_url_value is an empty string
        return "Unknown"

    temp_base_url = base_url_value

    # Validate base_url before parsing
    if not isinstance(temp_base_url, str) or not temp_base_url.strip():
        _LOGGER.warning(f"API client base_url is not a valid string: {temp_base_url!r}")
        return DIAGNOSTICS_REDACTED_PLACEHOLDER

    temp_base_url_with_scheme = (
        temp_base_url if "://" in temp_base_url else f"http://{temp_base_url}"
    )

    try:
        parsed_url = urlparse(temp_base_url_with_scheme)
        host_part = parsed_url.hostname
        port_part = parsed_url.port
    except Exception as exc:
        _LOGGER.warning(
            f"Exception occurred while parsing API client base_url '{temp_base_url}': {exc}"
        )
        return DIAGNOSTICS_REDACTED_PLACEHOLDER

    # Should not happen if base_url is valid and scheme is prepended.
    if host_part is None:
        _LOGGER.warning(f"Could not parse hostname from API client base_url: {temp_base_url}")
        return DIAGNOSTICS_REDACTED_PLACEHOLDER

    redacted_host_part = host_part
    successfully_redacted_sensitive_host = False

    if sensitive_host_ip:
        # Redact specific sensitive host (IP/hostname), handling IPv6 brackets.
        # The pattern ensures that if sensitive_host_ip is "1.2.3.4", it matches "1.2.3.4" but not "11.2.3.4".
        sensitive_pattern = r"(\[?" + re.escape(sensitive_host_ip) + r"\]?)"
        new_host_part_after_sensitive_redaction, num_subs_sensitive = re.subn(
            sensitive_pattern, DIAGNOSTICS_REDACTED_PLACEHOLDER, host_part, flags=re.IGNORECASE
        )
        if num_subs_sensitive > 0:
            redacted_host_part = new_host_part_after_sensitive_redaction
            successfully_redacted_sensitive_host = True
            _LOGGER.debug(f"Redacted sensitive host '{sensitive_host_ip}' in API base URL.")

    if not successfully_redacted_sensitive_host:
        # If not specifically redacted, check if host_part is any other IP address.
        try:
            ipaddress.ip_address(host_part)  # Raises ValueError if not a valid IP.
            redacted_host_part = DIAGNOSTICS_REDACTED_PLACEHOLDER
            _LOGGER.debug(f"Redacted generic IP address '{host_part}' in API base URL.")
        except ValueError:
            # Not a generic IP (e.g., a hostname not caught by sensitive_host_ip).
            _LOGGER.debug(
                f"Host part '{host_part}' is not a generic IP address and was not redacted as such."
            )
    REDACTED_PATH_PLACEHOLDER = "/REDACTED_PATH"
    REDACTED_QUERY_PLACEHOLDER = "REDACTED_QUERY"

    # Redact path if non-empty and not root; empty path (e.g. http://host) is valid.
    redacted_path = (
        REDACTED_PATH_PLACEHOLDER if parsed_url.path and parsed_url.path != "/" else parsed_url.path
    )
    redacted_query = REDACTED_QUERY_PLACEHOLDER if parsed_url.query else parsed_url.query

    userinfo_part = ""
    if parsed_url.username:
        userinfo_part = DIAGNOSTICS_REDACTED_PLACEHOLDER
        if parsed_url.password:
            userinfo_part += f":{DIAGNOSTICS_REDACTED_PLACEHOLDER}"
        userinfo_part += "@"
    redacted_netloc = (
        f"{userinfo_part}{redacted_host_part}{f':{port_part}' if port_part is not None else ''}"
    )

    return urlunparse(
        parsed_url._replace(netloc=redacted_netloc, path=redacted_path, query=redacted_query)
    )  # params and fragment are usually not sensitive but are kept by _replace if not specified


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
    return [
        {
            "entity_id": entity.entity_id,
            "unique_id": entity.unique_id,
            "platform": entity.platform,
            "disabled_by": entity.disabled_by,
        }
        for entity in entities
    ]
