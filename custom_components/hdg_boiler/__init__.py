"""
Main entry point for the HDG Bavaria Boiler integration.

This module handles the initialization of the integration when a config entry
is added to Home Assistant. It sets up the API client, data update coordinator,
and forwards the setup to relevant platforms (e.g., sensor, number).
Additionally, it registers custom services for interacting with the boiler and
manages their lifecycle during entry unload.
"""

__version__ = "0.9.5"

import functools
import logging
from typing import cast

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryNotReady
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .api import HdgApiClient
from .const import (
    CONF_HOST_IP,
    DOMAIN,
    SERVICE_GET_NODE_VALUE,
    SERVICE_SET_NODE_VALUE,
)
from .coordinator import HdgDataUpdateCoordinator
from .services import async_handle_get_node_value, async_handle_set_node_value
from .utils import prepare_base_url

_LOGGER = logging.getLogger(DOMAIN)

PLATFORMS: list[Platform] = [Platform.SENSOR, Platform.NUMBER]


def _register_services(
    hass: HomeAssistant, coordinator: HdgDataUpdateCoordinator
) -> None:
    """Register integration-specific services with Home Assistant."""
    bound_set_node_value_handler = functools.partial(
        async_handle_set_node_value, hass, coordinator
    )
    hass.services.async_register(
        DOMAIN, SERVICE_SET_NODE_VALUE, bound_set_node_value_handler
    )

    bound_get_node_value_handler = functools.partial(
        async_handle_get_node_value, hass, coordinator
    )
    hass.services.async_register(
        DOMAIN,
        SERVICE_GET_NODE_VALUE,
        bound_get_node_value_handler,
    )


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up the HDG Bavaria Boiler integration from a config entry."""
    hass.data.setdefault(DOMAIN, {})

    host_ip_original = entry.data[CONF_HOST_IP]
    base_url = prepare_base_url(host_ip_original)
    if not base_url:
        # ConfigEntryNotReady informs HA that setup cannot proceed
        # and should be retried or reconfigured by the user.
        _LOGGER.error(
            f"Failed to prepare base URL from host_ip '{host_ip_original}' for HDG Boiler. Please check configuration."
        )
        raise ConfigEntryNotReady(f"Invalid host/IP for HDG Boiler: {host_ip_original}")

    session = async_get_clientsession(hass)
    api_client = HdgApiClient(session, base_url)
    coordinator = HdgDataUpdateCoordinator(hass, api_client, entry)

    try:
        await coordinator.async_config_entry_first_refresh()
    except ConfigEntryNotReady:
        _LOGGER.error(
            f"Initial data refresh failed for {entry.title} (ConfigEntryNotReady). Setup will be retried by Home Assistant."
        )
        raise  # Re-raise to allow HA to handle retry
    except Exception as exc:
        _LOGGER.exception(
            f"Unexpected error during initial data refresh for {entry.title}: {exc}. Setup failed."
        )
        raise

    hass.data[DOMAIN][entry.entry_id] = {
        "coordinator": coordinator,
        "api_client": api_client,
    }

    # Start the set_value worker task as a background task tied to the config entry.
    # This ensures HA doesn't wait for it during startup.
    coordinator._set_value_worker_task = entry.async_create_background_task(
        hass,
        coordinator._set_value_worker(),  # Pass the coroutine to be executed
        name=f"{DOMAIN}_{entry.entry_id}_set_value_worker",  # Descriptive name for the task
    )
    _LOGGER.info(
        f"HDG set_value_worker background task created for entry {entry.title}."
    )

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    _register_services(hass, coordinator)
    entry.async_on_unload(entry.add_update_listener(async_options_update_listener))

    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """
    Unload a config entry.

    This is called when an integration instance is removed from Home Assistant.
    It unloads associated platforms and cleans up resources, including services.
    """
    _LOGGER.info(f"Unloading HDG Boiler integration for {entry.title}")

    # Retrieve coordinator before popping it from hass.data
    integration_data = hass.data[DOMAIN].get(entry.entry_id)
    coordinator: HdgDataUpdateCoordinator | None = (
        integration_data.get("coordinator") if integration_data else None
    )
    # Cast to bool to satisfy mypy, as async_unload_platforms is expected to return bool. # type: ignore[no-untyped-call] # async_unload_platforms is typed elsewhere
    unload_ok = cast(
        bool, await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    )

    if unload_ok:
        if entry.entry_id in hass.data[DOMAIN]:
            # Gracefully stop the set_value_worker if coordinator exists
            if coordinator:
                await coordinator.async_stop_set_value_worker()
            hass.data[DOMAIN].pop(entry.entry_id)
            _LOGGER.debug(f"Removed {entry.entry_id} data from hass.data.{DOMAIN}")

        if not hass.data[DOMAIN]:
            _LOGGER.info(f"Last entry for {DOMAIN} unloaded, removing services.")
            hass.services.async_remove(DOMAIN, SERVICE_SET_NODE_VALUE)
            hass.services.async_remove(DOMAIN, SERVICE_GET_NODE_VALUE)

    return unload_ok


async def async_options_update_listener(
    hass: HomeAssistant, entry: ConfigEntry
) -> None:
    """
    Handle options update.

    This listener is called when the integration's options are changed via the UI.
    It reloads the config entry to apply the new options.
    """
    _LOGGER.info(
        f"Configuration options for {entry.title} updated: {entry.options}. Reloading entry."
    )
    await hass.config_entries.async_reload(entry.entry_id)
