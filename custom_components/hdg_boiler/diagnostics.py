"""
Diagnostics support for the HDG Bavaria Boiler integration.

This module provides functionality to gather and return diagnostic information
about the integration's configuration, state, and connected entities,
aiding in troubleshooting and support.
"""

from __future__ import annotations

__version__ = "0.8.0"

from typing import Any, Dict

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.components.diagnostics import async_redact_data
from homeassistant.util import dt as dt_util  # Date/time utilities for timezone conversions.

from .const import DOMAIN, CONF_HOST_IP
from .coordinator import HdgDataUpdateCoordinator
from .api import HdgApiClient

# Defines a set of configuration keys whose values will be automatically redacted
# from the diagnostics output to protect sensitive information like IP addresses.
TO_REDACT = {
    CONF_HOST_IP,
    # Add other keys such as API tokens or passwords here if they are introduced in the future.
}

# Defines a set of HDG Node IDs (base IDs, without T/U/V/W/X/Y suffix) whose values,
# if ever directly included from coordinator.data in diagnostics, should be redacted.
SENSITIVE_COORDINATOR_DATA_NODE_IDS = {
    "20026",  # Corresponds to anlagenbezeichnung_sn (Boiler Serial Number)
    "20031",  # Corresponds to mac_adresse (MAC Address)
    "20039",  # Corresponds to hydraulikschema_nummer (Hydraulic Scheme Number)
}


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: ConfigEntry
) -> Dict[str, Any]:
    """
    Generate and return diagnostics data for a given config entry.

    This data includes redacted configuration, coordinator status, API client details,
    and information about associated entities, which helps in troubleshooting
    and understanding the integration's current operational state.
    """
    diag_data: Dict[str, Any] = {}

    # Retrieve the integration-specific data (coordinator, API client) stored in hass.data.
    # This data is populated during the integration's setup process in __init__.py.
    integration_data = hass.data[DOMAIN].get(entry.entry_id)
    if not integration_data:
        # If data is not found, it might indicate an incomplete or failed setup.
        # Returning an error message helps diagnose this scenario.
        return {"error": "Integration data not found. Setup might not have completed successfully."}

    coordinator: HdgDataUpdateCoordinator = integration_data.get("coordinator")
    api_client: HdgApiClient = integration_data.get("api_client")

    # Identify sensitive information from the config entry for manual redaction checks.
    # This is particularly important for values that might be part of constructed strings (e.g., URLs)
    # or used as unique identifiers, which `async_redact_data` might not cover if the key itself isn't in TO_REDACT.
    sensitive_host_ip = entry.data.get(CONF_HOST_IP)
    redacted_placeholder = "REDACTED"  # Standard placeholder for redacted values.

    # Redact the config entry's unique_id if it's identical to the sensitive host_ip.
    # This is a proactive measure to prevent accidental exposure of the host_ip
    # if it was used (e.g., in older versions or by user choice) to form the unique_id.
    unique_id_display = entry.unique_id
    if (
        sensitive_host_ip
        and entry.unique_id  # Check if unique_id exists and is not None.
        and entry.unique_id.lower() == sensitive_host_ip.lower()
    ):
        unique_id_display = redacted_placeholder

    diag_data["config_entry"] = {
        "title": entry.title,
        "entry_id": entry.entry_id,
        # Use Home Assistant's built-in helper to redact sensitive values from config entry data and options
        # based on the keys defined in TO_REDACT.
        "data": async_redact_data(entry.data, TO_REDACT),
        "options": async_redact_data(entry.options, TO_REDACT),
        "unique_id": unique_id_display,  # Show the potentially redacted unique_id.
    }

    if coordinator:
        # Include key information about the data update coordinator's status and data.
        diag_data["coordinator"] = {
            "last_update_success": coordinator.last_update_success,
            "last_update_time_successful": (
                # Format timestamp as ISO string for better readability and machine processing.
                # This represents the time of the last successful data fetch.
                coordinator.last_update_success_time.isoformat()
                if coordinator.last_update_success_time
                else None
            ),
            # Provide a sample of keys from the coordinator's data store (node_id: raw_value)
            # To ensure sensitive values are not accidentally exposed, even if only keys are sampled,
            # we operate on a redacted copy of the coordinator's data.
            "data_sample_keys": [],
            "data_item_count": 0,
            # Display the scan intervals (in seconds) currently configured and used by the coordinator
            # for each polling group.
            "scan_intervals_used": {
                str(k): v.total_seconds() for k, v in coordinator.scan_intervals.items()
            },
            # Convert float timestamps (seconds since epoch, as stored by coordinator)
            # to ISO formatted UTC datetime strings for consistent diagnostic output.
            # These indicate the last time each specific polling group was successfully updated.
            "last_group_update_times": {
                group_key: dt_util.utc_from_timestamp(timestamp).isoformat()
                for group_key, timestamp in coordinator._last_update_times.items()
                if isinstance(
                    timestamp, (int, float)
                )  # Ensure timestamp is numeric before conversion.
            },
        }
        if coordinator.data:
            # Redact sensitive node values from a copy of the coordinator's data
            # before extracting any information from it for diagnostics.
            redacted_coordinator_data = async_redact_data(
                coordinator.data, SENSITIVE_COORDINATOR_DATA_NODE_IDS
            )
            diag_data["coordinator"]["data_sample_keys"] = list(redacted_coordinator_data.keys())[
                :20
            ]
            diag_data["coordinator"]["data_item_count"] = len(redacted_coordinator_data)
            # If you ever decide to include full coordinator.data, use redacted_coordinator_data.
    else:
        diag_data["coordinator"] = "Coordinator not found or not initialized."

    if api_client:
        # Manually redact the sensitive host IP if it's part of the API client's base URL.
        # This is a specific check because the `_base_url` is constructed within the API client
        # and might not be directly covered by `async_redact_data` if `_base_url` itself isn't a config key.
        base_url_display = "Unknown"
        if hasattr(api_client, "_base_url") and api_client._base_url:
            temp_base_url = api_client._base_url
            if sensitive_host_ip and sensitive_host_ip in temp_base_url:
                base_url_display = temp_base_url.replace(sensitive_host_ip, redacted_placeholder)
            else:
                # Use the original base_url if no redaction is needed (e.g., IP not found) or possible.
                base_url_display = temp_base_url

        diag_data["api_client"] = {"base_url": base_url_display}

        # Example: Include a live connectivity check in diagnostics.
        # This is commented out by default because network calls within diagnostics can be slow
        # or error-prone, potentially hindering the diagnostic data collection itself or causing timeouts.
        # It should be used with caution and might be better suited for a separate service call or tool.
        # try:
        #     if hasattr(api_client, 'async_check_connectivity'):
        #         diag_data["api_client"]["live_connectivity_check"] = await api_client.async_check_connectivity()
        # except Exception as e:
        #     diag_data["api_client"]["live_connectivity_check_error"] = str(e)
    else:
        diag_data["api_client"] = "API Client not found or not initialized."

    # Include information about entities associated with this config entry from the Home Assistant entity registry.
    # This helps in understanding which entities are currently managed by this instance of the integration.
    entity_registry = await hass.helpers.entity_registry.async_get_registry()
    entities = [
        {
            "entity_id": entity.entity_id,
            "unique_id": entity.unique_id,  # Helps correlate with SENSOR_DEFINITIONS if translation_key is used for unique_id_suffix
            "platform": entity.platform,
            "disabled_by": entity.disabled_by,  # Indicates if the entity is disabled by user or integration
        }
        for entity in entity_registry.entities.get_entries_for_config_entry_id(entry.entry_id)
    ]
    diag_data["entities"] = entities

    return diag_data
