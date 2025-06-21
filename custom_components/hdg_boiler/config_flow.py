"""Configuration flow for the HDG Bavaria Boiler integration."""

from __future__ import annotations

__version__ = "0.9.35"

import logging
from typing import Any
from urllib.parse import urlparse

import async_timeout
import homeassistant.helpers.config_validation as cv
import voluptuous as vol
from homeassistant import config_entries, core
from homeassistant.core import callback
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from voluptuous.schema_builder import Marker

from .api import (
    HdgApiClient,
    HdgApiConnectionError,
    HdgApiError,
)
from .const import (
    CONF_DEVICE_ALIAS,
    CONF_ENABLE_DEBUG_LOGGING,
    CONF_HOST_IP,
    CONF_SOURCE_TIMEZONE,
    CONFIG_FLOW_API_TIMEOUT,
    CONFIG_FLOW_TEST_PAYLOAD,
    DEFAULT_ENABLE_DEBUG_LOGGING,
    DEFAULT_SOURCE_TIMEZONE,
    DOMAIN,
    MAX_SCAN_INTERVAL,
    MIN_SCAN_INTERVAL,
    POLLING_GROUP_DEFINITIONS,
)
from .helpers.network_utils import async_execute_icmp_ping


_LOGGER = logging.getLogger(DOMAIN)


@config_entries.HANDLERS.register(DOMAIN)
class HdgBoilerConfigFlow(config_entries.ConfigFlow):
    """Handle a config flow for HDG Bavaria Boiler."""

    USER_DATA_SCHEMA = vol.Schema(
        {
            vol.Required(CONF_HOST_IP): str,
            vol.Optional(CONF_DEVICE_ALIAS, default=""): cv.string,
        }
    )

    def _create_options_schema(
        self, options: config_entries.Mapping[str, Any] | None = None
    ) -> vol.Schema:
        """Generate the schema for the options flow."""
        current_options = options or {}
        options_schema_dict: dict[Marker, Any] = {}

        for group_def in POLLING_GROUP_DEFINITIONS:
            config_key = group_def["config_key"]  # type: ignore[misc]
            default_interval = group_def["default_interval"]  # type: ignore[misc]

            options_schema_dict[
                vol.Optional(
                    config_key,
                    default=current_options.get(config_key, default_interval),
                )
            ] = vol.All(
                cv.positive_int,
                vol.Range(
                    min=MIN_SCAN_INTERVAL,
                    max=MAX_SCAN_INTERVAL,
                    msg="scan_interval_invalid_range_min_max",
                ),
            )

        options_schema_dict |= {
            vol.Optional(
                CONF_ENABLE_DEBUG_LOGGING,
                default=current_options.get(
                    CONF_ENABLE_DEBUG_LOGGING, DEFAULT_ENABLE_DEBUG_LOGGING
                ),
            ): cv.boolean,
            vol.Optional(
                CONF_SOURCE_TIMEZONE,
                default=current_options.get(
                    CONF_SOURCE_TIMEZONE, DEFAULT_SOURCE_TIMEZONE
                ),
            ): str,
        }
        return vol.Schema(options_schema_dict)

    def _get_description_placeholders(self) -> dict[str, str]:
        """Return placeholders for the options form description."""
        placeholders = {
            "min_scan_interval": str(MIN_SCAN_INTERVAL),
            "max_scan_interval": str(MAX_SCAN_INTERVAL),
        }
        # Dynamically create placeholders for default scan intervals
        # based on POLLING_GROUP_DEFINITIONS.
        # The placeholder keys in strings.json (e.g., "default_group_1_realtime_core")
        # must match the config_key from POLLING_GROUP_DEFINITIONS with "default_" prefix.
        for group_def in POLLING_GROUP_DEFINITIONS:
            placeholder_key = f"default_{group_def['config_key']}"  # type: ignore[misc]
            placeholders[placeholder_key] = str(group_def["default_interval"])  # type: ignore[misc]
        return placeholders

    async def validate_host_connectivity(
        self, hass: core.HomeAssistant, host_ip: str
    ) -> bool:
        """Validate connectivity to the HDG boiler."""

        # Step 1: Perform an ICMP Ping to check basic host reachability.
        # This requires extracting the hostname from the provided host_ip.
        # HdgApiClient's constructor normalizes the host_ip.
        # to reliably parse it and extract the hostname, while also validating
        # the host_ip format early in the process.
        try:
            # Create a temporary client just to get the parsed base_url for hostname extraction.
            # This also validates the host_ip format early.
            temp_api_client_for_url = HdgApiClient(
                async_get_clientsession(hass), host_ip
            )
            parsed_url = urlparse(temp_api_client_for_url.base_url)
            host_to_ping = parsed_url.hostname
        except HdgApiError as e:  # Catch errors from HdgApiClient constructor (e.g. invalid host_ip format)
            _LOGGER.warning(
                f"Invalid host_ip format '{host_ip}' for API client construction: {e}"
            )
            return False  # Cannot proceed if host_ip is fundamentally invalid for the API client.

        if not host_to_ping:
            _LOGGER.error(
                f"Could not extract hostname from host_ip '{host_ip}' for ICMP ping."
            )
            return False

        if not await async_execute_icmp_ping(host_to_ping, timeout_seconds=3):
            _LOGGER.warning(f"ICMP ping to {host_to_ping} (from IP: {host_ip}) failed.")
            return False
        _LOGGER.debug(f"ICMP ping to {host_to_ping} (from IP: {host_ip}) successful.")

        # Step 2: Attempt to fetch minimal known HDG nodes to verify it's an HDG device.
        # This step confirms that the device at the given IP address not only responds
        # to pings but also behaves like an HDG boiler by responding to a specific API request.
        session = async_get_clientsession(hass)
        temp_api_client = HdgApiClient(session, host_ip)

        try:
            async with async_timeout.timeout(CONFIG_FLOW_API_TIMEOUT):
                test_payload_str = CONFIG_FLOW_TEST_PAYLOAD
                _LOGGER.debug(
                    f"Attempting to fetch test nodes ({test_payload_str}) from {host_ip}"
                )
                test_data = await temp_api_client.async_get_nodes_data(test_payload_str)

                if test_data and isinstance(test_data, list) and len(test_data) >= 1:
                    # Basic check: if we get a list with at least one item, assume it's an HDG device.
                    # A more robust check could verify the structure of test_data[0].
                    _LOGGER.debug(
                        "Successfully fetched test nodes from %s. Device is likely an HDG boiler.",
                        host_ip,
                    )
                    return True
                _LOGGER.warning(
                    "Failed to fetch test nodes or received empty/invalid data from %s. Device might not be an HDG boiler.",
                    host_ip,
                )
                return False
        except (HdgApiConnectionError, HdgApiError) as err:
            _LOGGER.warning(
                "API error during HDG device check for %s: %s", host_ip, err
            )
        except TimeoutError:  # Catches asyncio.TimeoutError from async_timeout
            _LOGGER.warning("Timeout during HDG device check for %s.", host_ip)
        except Exception as err:  # pylint: disable=broad-except
            _LOGGER.exception(
                "Unexpected error during HDG device check for %s: %s", host_ip, err
            )
        return False

    VERSION = 1

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.ConfigFlowResult:
        """Handle the initial user step."""
        _LOGGER.debug("async_step_user called with user_input: %s", user_input)
        errors: dict[str, str] = {}

        if user_input is not None:
            host_ip = user_input.get(CONF_HOST_IP)
            current_device_alias = user_input.get(CONF_DEVICE_ALIAS, "")

            if not host_ip:
                errors["base"] = "host_ip_required"
            else:
                is_hdg_device_and_connected = await self.validate_host_connectivity(
                    self.hass, host_ip
                )
                if is_hdg_device_and_connected:
                    # At this point, the host is reachable and responded like an HDG device.
                    _LOGGER.info(f"Successfully validated HDG device at {host_ip}.")
                    await self.async_set_unique_id(host_ip.lower())
                    # If unique_id already exists, this will raise AbortFlow and stop here.
                    self._abort_if_unique_id_configured()

                    _LOGGER.debug("Creating entry for host_ip: %s", host_ip)
                    return self.async_create_entry(
                        title=current_device_alias or f"HDG Boiler ({host_ip})",
                        data=user_input,
                    )
                else:
                    # This error covers both "cannot connect (ping failed)" and "not an HDG device (API test failed)".
                    # For a more specific UI message, validate_host_connectivity could return different error types/codes.
                    _LOGGER.warning(
                        f"Validation failed for host {host_ip}. It's either not reachable or not a recognized HDG device."
                    )
                    errors["base"] = "cannot_connect"
        data_schema_user = self.USER_DATA_SCHEMA
        # Pre-fill form with previous input if validation failed
        if user_input:
            data_schema_user = vol.Schema(
                {
                    vol.Required(
                        CONF_HOST_IP, default=user_input.get(CONF_HOST_IP, "")
                    ): str,
                    vol.Optional(
                        CONF_DEVICE_ALIAS,
                        default=user_input.get(CONF_DEVICE_ALIAS, ""),
                    ): str,
                }
            )

        return self.async_show_form(
            step_id="user",
            data_schema=data_schema_user,
            errors=errors,
        )

    @staticmethod
    @callback
    def async_get_options_flow(
        config_entry: config_entries.ConfigEntry,
    ) -> HdgBoilerOptionsFlowHandler:
        """Get the options flow for this handler."""
        _LOGGER.debug(
            "async_get_options_flow called for entry: %s", config_entry.entry_id
        )
        return HdgBoilerOptionsFlowHandler(config_entry)


class HdgBoilerOptionsFlowHandler(config_entries.OptionsFlow):
    """Handle an options flow for HDG Bavaria Boiler."""

    def __init__(self, config_entry: config_entries.ConfigEntry) -> None:
        """Initialize options flow."""
        super().__init__()
        self.config_entry = config_entry
        _LOGGER.debug(
            "HdgBoilerOptionsFlowHandler initialized for entry: %s",
            config_entry.entry_id,
        )

    def _get_options_schema(self) -> vol.Schema:
        """Get the options schema.

        This creates a temporary instance of the main config flow to reuse its schema creation logic.
        This is a workaround; a more robust solution might involve static methods or duplicated logic.
        """
        flow_instance = HdgBoilerConfigFlow()
        # Access config_entry directly from self, provided by the base class
        return flow_instance._create_options_schema(self.config_entry.options)

    def _get_options_description_placeholders(self) -> dict[str, str]:
        """Get description placeholders for the options form.

        Similar to _get_options_schema, it reuses logic from the main config flow.
        """
        flow_instance = HdgBoilerConfigFlow()
        return flow_instance._get_description_placeholders()

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.ConfigFlowResult:
        """Manage minimal options."""
        _LOGGER.debug(
            "OptionsFlow async_step_init called with user_input: %s", user_input
        )
        current_errors: dict[str, str] = {}

        if user_input is not None:
            # Options are directly saved without further validation in this simple flow.
            _LOGGER.debug(
                "Options flow: Creating entry with new options: %s", user_input
            )
            return self.async_create_entry(title="", data=user_input)

        options_schema = self._get_options_schema()

        return self.async_show_form(
            step_id="init",
            data_schema=options_schema,
            errors=current_errors,
            description_placeholders=self._get_options_description_placeholders(),
        )
