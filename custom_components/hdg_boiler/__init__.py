"""
The HDG Bavaria Boiler integration.

This component sets up the HDG Bavaria Boiler integration, initializing the API client,
data update coordinator, and associated platforms (sensor, number). It also handles
the registration and unregistration of custom services.
"""

__version__ = "0.7.0"

import logging
import functools

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryNotReady
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .api import HdgApiClient
from .const import (
    DOMAIN,
    CONF_HOST_IP,
    SERVICE_SET_NODE_VALUE,
    SERVICE_GET_NODE_VALUE,
)
from .coordinator import HdgDataUpdateCoordinator
from .services import async_handle_set_node_value, async_handle_get_node_value

_LOGGER = logging.getLogger(DOMAIN)

# Define the platforms that this integration will set up.
PLATFORMS: list[Platform] = [Platform.SENSOR, Platform.NUMBER]


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up HDG Bavaria Boiler from a config entry."""
    # Ensure a central dictionary for this integration's data exists in `hass.data`.
    # This dictionary will store the coordinator and API client, keyed by config entry ID.
    hass.data.setdefault(DOMAIN, {})

    host_ip = entry.data[CONF_HOST_IP]
    # Construct the base URL for the API client. If the user-provided host_ip
    # doesn't include a scheme, prepend "http://".
    base_url = host_ip if host_ip.startswith(("http://", "https://")) else f"http://{host_ip}"

    # Get a shared aiohttp client session from Home Assistant.
    session = async_get_clientsession(hass)
    # Initialize the API client with the session and base URL.
    # The HdgApiClient handles all communication with the HDG boiler's web interface.
    api_client = HdgApiClient(session, base_url)

    # Create the data update coordinator.
    # The HdgDataUpdateCoordinator is responsible for periodically fetching data
    # from the API and providing it to entities.
    coordinator = HdgDataUpdateCoordinator(hass, api_client, entry)

    # Perform the initial data refresh. If this fails, ConfigEntryNotReady is raised,
    # and Home Assistant will automatically retry the setup later. This is crucial
    # to ensure the integration doesn't start in a broken state if the boiler is initially unreachable.
    try:
        await coordinator.async_config_entry_first_refresh()
    except ConfigEntryNotReady:
        _LOGGER.error(
            f"Initial data refresh failed for {entry.title}. Setup will be retried by Home Assistant."
        )
        return False

    # Store the coordinator and API client in `hass.data` for access by platforms (sensor, number).
    # This allows platform setup functions to retrieve these shared instances.
    hass.data[DOMAIN][entry.entry_id] = {"coordinator": coordinator, "api_client": api_client}

    # Forward the setup to the defined platforms (sensor, number).
    # This will call the `async_setup_entry` function in `sensor.py` and `number.py`.
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    # Register integration-specific services.
    # functools.partial is used to pre-fill the 'hass' and 'coordinator' arguments
    # for the service handler functions, as Home Assistant service calls only pass the 'call' object.
    # This binds the necessary context to the handlers.
    bound_set_node_value_handler = functools.partial(async_handle_set_node_value, hass, coordinator)
    hass.services.async_register(DOMAIN, SERVICE_SET_NODE_VALUE, bound_set_node_value_handler)

    bound_get_node_value_handler = functools.partial(async_handle_get_node_value, hass, coordinator)
    hass.services.async_register(DOMAIN, SERVICE_GET_NODE_VALUE, bound_get_node_value_handler)

    # Set up a listener for options flow updates. If options change, the entry will be reloaded.
    # This ensures that changes made via the "Configure" UI for the integration
    # (e.g., scan intervals) are applied by reloading the integration.
    entry.async_on_unload(entry.add_update_listener(async_options_update_listener))
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    _LOGGER.info(f"Unloading HDG Boiler integration for {entry.title}")

    # Unload platforms (sensor, number) associated with this config entry.
    # This calls the `async_unload_entry` function in the respective platform files.
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)

    if unload_ok:
        # Clean up `hass.data` for this specific entry to free resources.
        if entry.entry_id in hass.data[DOMAIN]:
            hass.data[DOMAIN].pop(entry.entry_id)
            _LOGGER.debug(f"Removed {entry.entry_id} data from hass.data.{DOMAIN}")

        # If this was the last config entry for this domain, remove the services.
        # This prevents services from being orphaned if the integration is fully removed
        # and no other instances of this integration are running.
        if not hass.data[DOMAIN]:
            _LOGGER.info(f"Last entry for {DOMAIN} unloaded, removing services.")
            hass.services.async_remove(DOMAIN, SERVICE_SET_NODE_VALUE)
            hass.services.async_remove(DOMAIN, SERVICE_GET_NODE_VALUE)

    return unload_ok


async def async_options_update_listener(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Handle options update by reloading the config entry."""
    _LOGGER.info(
        f"Configuration options for {entry.title} updated: {entry.options}. Reloading entry."
    )
    # Reload the config entry to apply the new options. This will trigger `async_unload_entry`
    # followed by `async_setup_entry` with the updated configuration.
    await hass.config_entries.async_reload(entry.entry_id)
