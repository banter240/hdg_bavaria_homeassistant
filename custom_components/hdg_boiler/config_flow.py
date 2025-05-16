"""
Config flow for HDG Bavaria Boiler integration.

This module handles the configuration process for the HDG Bavaria Boiler integration,
enabling users to establish a connection to their boiler through the Home Assistant UI.
It encompasses initial setup steps (host IP, device alias) and an options flow
for modifying settings such as scan intervals and debug logging after the initial setup.
"""

__version__ = "0.9.0"

import logging
from typing import Any, Dict, Optional

import voluptuous as vol
from homeassistant import config_entries, core
from homeassistant.core import callback
from homeassistant.helpers.aiohttp_client import async_get_clientsession
import homeassistant.helpers.config_validation as cv

from .const import (
    DOMAIN,
    DEFAULT_NAME,
    CONF_HOST_IP,
    CONF_SCAN_INTERVAL_GROUP1,
    CONF_DEVICE_ALIAS,
    CONF_SCAN_INTERVAL_GROUP2,
    CONF_SCAN_INTERVAL_GROUP3,
    CONF_SCAN_INTERVAL_GROUP4,
    CONF_SCAN_INTERVAL_GROUP5,
    DEFAULT_SCAN_INTERVAL_GROUP1,
    DEFAULT_SCAN_INTERVAL_GROUP2,
    DEFAULT_SCAN_INTERVAL_GROUP3,
    DEFAULT_SCAN_INTERVAL_GROUP4,
    DEFAULT_SCAN_INTERVAL_GROUP5,
    CONF_ENABLE_DEBUG_LOGGING,
    DEFAULT_ENABLE_DEBUG_LOGGING,
    HDG_NODE_PAYLOADS,
)

_LOGGER = logging.getLogger(DOMAIN)

# Schema for user input during the initial configuration step.
USER_DATA_SCHEMA = vol.Schema(
    {
        # Host IP address or hostname of the HDG boiler device.
        vol.Required(CONF_HOST_IP): str,
        vol.Optional(CONF_DEVICE_ALIAS): str,  # User-defined alias for the device.
    }
)


def _create_options_schema(options: Optional[Dict[str, Any]] = None) -> vol.Schema:
    """
    Generate schema for options flow, pre-filling with existing options.

    Constructs the schema for the options configuration form, using existing
    options (if any) as default values. This ensures a consistent user
    experience when reconfiguring.
    """
    options = options or {}
    return vol.Schema(
        {
            # Scan interval for the "Realtime Core" data polling group.
            vol.Optional(
                CONF_SCAN_INTERVAL_GROUP1,
                default=options.get(CONF_SCAN_INTERVAL_GROUP1, DEFAULT_SCAN_INTERVAL_GROUP1),
            ): cv.positive_int,
            # Scan interval for the "General Status" data polling group.
            vol.Optional(
                CONF_SCAN_INTERVAL_GROUP2,
                default=options.get(CONF_SCAN_INTERVAL_GROUP2, DEFAULT_SCAN_INTERVAL_GROUP2),
            ): cv.positive_int,
            # Scan interval for the "Config/Counters 1" data polling group.
            vol.Optional(
                CONF_SCAN_INTERVAL_GROUP3,
                default=options.get(CONF_SCAN_INTERVAL_GROUP3, DEFAULT_SCAN_INTERVAL_GROUP3),
            ): cv.positive_int,
            # Scan interval for the "Config/Counters 2" data polling group.
            vol.Optional(
                CONF_SCAN_INTERVAL_GROUP4,
                default=options.get(CONF_SCAN_INTERVAL_GROUP4, DEFAULT_SCAN_INTERVAL_GROUP4),
            ): cv.positive_int,
            # Scan interval for the "Config/Counters 3" data polling group.
            vol.Optional(
                CONF_SCAN_INTERVAL_GROUP5,
                default=options.get(CONF_SCAN_INTERVAL_GROUP5, DEFAULT_SCAN_INTERVAL_GROUP5),
            ): cv.positive_int,
            # Option to enable/disable detailed debug logging for coordinator's polling cycles.
            vol.Optional(
                CONF_ENABLE_DEBUG_LOGGING,
                default=options.get(CONF_ENABLE_DEBUG_LOGGING, DEFAULT_ENABLE_DEBUG_LOGGING),
            ): cv.boolean,
        }
    )


async def validate_host_connectivity(hass: core.HomeAssistant, host_ip: str) -> bool:
    """
    Verify host reachability and HDG boiler response via a basic API call.

    Performs an API call to ascertain connectivity and device compatibility.
    """
    start_time_validation = hass.loop.time()
    # Import HdgApiClient locally to prevent circular dependencies at the module level,
    # as api.py might import from const.py which could be involved in config_flow.py.
    from .api import (
        HdgApiClient,
        HdgApiError,
    )

    _LOGGER.debug(f"validate_host_connectivity: Starting validation for host_ip: {host_ip}")
    session = async_get_clientsession(hass)
    # HdgApiClient formats the base_url (e.g., adds http://).
    # Temporary instance for validation purposes only.
    temp_api_client = HdgApiClient(session, host_ip)

    try:
        _LOGGER.debug(
            f"validate_host_connectivity: Attempting HdgApiClient.async_check_connectivity() to {host_ip}"
        )
        start_time_check_connectivity = hass.loop.time()
        is_connected = await temp_api_client.async_check_connectivity()
        end_time_check_connectivity = hass.loop.time()
        duration_check_connectivity = end_time_check_connectivity - start_time_check_connectivity
        _LOGGER.debug(
            f"validate_host_connectivity: HdgApiClient.async_check_connectivity() to {host_ip} "
            f"completed in {duration_check_connectivity:.2f}s. Result: {is_connected}"
        )

        if is_connected:
            _LOGGER.debug(f"validate_host_connectivity: Connectivity test to {host_ip} successful.")
            return True
        # If not connected, HdgApiClient.async_check_connectivity() returns False,
        # indicating host was reached but did not respond as an HDG boiler.
        _LOGGER.warning(
            f"validate_host_connectivity: Connectivity test to {host_ip} failed (HdgApiClient reported not connected)."
        )
        return False
    except HdgApiError as e:  # Catch specific API errors from HdgApiClient.
        _LOGGER.warning(
            f"validate_host_connectivity: API error during connectivity test to {host_ip}: {e}"
        )  # Log as warning for config flow validation.
        return False
    except Exception as e:  # Catch any other unexpected errors.
        _LOGGER.error(
            f"validate_host_connectivity: Unexpected error during connectivity test to {host_ip}: {e}"
        )
        return False
    finally:
        end_time_validation = hass.loop.time()
        duration_validation = end_time_validation - start_time_validation
        _LOGGER.debug(
            f"validate_host_connectivity: Finished validation for host_ip: {host_ip}. "
            f"Total duration: {duration_validation:.2f}s"
        )


class HdgBoilerConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for HDG Bavaria Boiler."""

    VERSION = 1  # Config flow version for future migrations.

    async def async_step_user(self, user_input: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """Handle the initial user-initiated step of the configuration flow."""
        errors: Dict[str, str] = {}

        if user_input is not None:
            # User has submitted the form; process input.
            host_ip = user_input[CONF_HOST_IP].strip()
            device_alias = user_input.get(CONF_DEVICE_ALIAS, "").strip()

            if not host_ip:
                # Host IP is required for setup.
                errors["base"] = "host_ip_required"
            else:
                # If alias provided, check for duplicates among existing HDG entries.
                if device_alias:
                    existing_entries = self.hass.config_entries.async_entries(DOMAIN)
                    for entry in existing_entries:
                        # Skip comparison if reconfiguring the current entry.
                        if (
                            self.handler == "options"
                            and self.config_entry is not None
                            and entry.entry_id == self.config_entry.entry_id
                        ):
                            continue
                        if (
                            entry.data.get(CONF_DEVICE_ALIAS, "").strip().lower()
                            == device_alias.lower()
                        ):
                            errors[CONF_DEVICE_ALIAS] = "alias_already_exists"
                            _LOGGER.warning(
                                f"Device alias '{device_alias}' is already in use by another entry."
                            )
                            break

            if (
                not errors
            ):  # Proceed if no input validation errors (missing host_ip, duplicate alias).
                is_connected = await validate_host_connectivity(self.hass, host_ip)
                if is_connected:
                    # No prior errors and connectivity validation passed.

                    # Set unique ID for config entry to prevent duplicates.
                    # host_ip.lower() ensures case-insensitivity.
                    await self.async_set_unique_id(host_ip.lower())
                    # Abort if config entry with this unique ID already exists.
                    self._abort_if_unique_id_configured()

                    # Prepare config data for storage.
                    # Defaults for scan intervals and debug logging applied on initial setup.
                    config_data: Dict[str, Any] = {
                        CONF_HOST_IP: host_ip,
                        CONF_SCAN_INTERVAL_GROUP1: DEFAULT_SCAN_INTERVAL_GROUP1,
                        CONF_SCAN_INTERVAL_GROUP2: DEFAULT_SCAN_INTERVAL_GROUP2,
                        CONF_SCAN_INTERVAL_GROUP3: DEFAULT_SCAN_INTERVAL_GROUP3,
                        CONF_SCAN_INTERVAL_GROUP4: DEFAULT_SCAN_INTERVAL_GROUP4,
                        CONF_SCAN_INTERVAL_GROUP5: DEFAULT_SCAN_INTERVAL_GROUP5,
                        CONF_ENABLE_DEBUG_LOGGING: DEFAULT_ENABLE_DEBUG_LOGGING,
                    }
                    # Include device alias (even if empty) to ensure key exists.
                    config_data[CONF_DEVICE_ALIAS] = device_alias

                    # Create config entry. Title uses alias or host_ip for UI.
                    return self.async_create_entry(
                        title=f"{DEFAULT_NAME} ({device_alias or host_ip})",
                        data=config_data,
                    )
                else:  # Connectivity validation failed.
                    errors["base"] = "cannot_connect"
            # Errors dictionary populated if initial errors or connectivity failed.

        # Define schema for user input form.
        # Defaults pre-fill form on error or for first display.
        data_schema = vol.Schema(
            {
                vol.Required(
                    CONF_HOST_IP,
                    default=user_input.get(CONF_HOST_IP, "") if user_input is not None else "",
                ): str,
                vol.Optional(
                    CONF_DEVICE_ALIAS,
                    default=user_input.get(CONF_DEVICE_ALIAS, "") if user_input is not None else "",
                ): str,
            }
        )
        return self.async_show_form(step_id="user", data_schema=data_schema, errors=errors)

    @staticmethod
    @callback
    def async_get_options_flow(
        config_entry: config_entries.ConfigEntry,
    ) -> config_entries.OptionsFlow:
        """
        Retrieve the options flow handler for this integration.

        Called by HA to get an instance of the options flow handler.
        OptionsFlowManager manages its lifecycle.
        """
        return HdgBoilerOptionsFlowHandler(config_entry)


class HdgBoilerOptionsFlowHandler(config_entries.OptionsFlow):
    """Handle an options flow for HDG Bavaria Boiler (scan intervals, debug logging)."""

    def __init__(self, config_entry: config_entries.ConfigEntry) -> None:
        """
        Initialize options flow.

        Config_entry passed by HA; stored for access to existing config/options.
        """
        self.config_entry = config_entry

    async def async_step_init(self, user_input: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """Manage options for scan intervals and debug logging."""
        errors: Dict[str, str] = {}

        if user_input is not None:
            # Form submitted; create new entry with updated options for HA to store.
            _LOGGER.debug(f"Updating options for {self.config_entry.title}: {user_input}")
            return self.async_create_entry(title="", data=user_input)

        # First time showing form; create schema using existing options to pre-fill.
        # self.config_entry provided by base OptionsFlow class.
        options_schema = _create_options_schema(self.config_entry.options)

        # Prepare placeholders for form description, matching translation keys
        # for dynamic content. Fallback names used if group not in HDG_NODE_PAYLOADS.
        description_placeholders: Dict[str, str] = {
            "default_realtime_core": str(DEFAULT_SCAN_INTERVAL_GROUP1),
            "default_status_general": str(DEFAULT_SCAN_INTERVAL_GROUP2),
            "default_config_counters_1": str(DEFAULT_SCAN_INTERVAL_GROUP3),
            "default_config_counters_2": str(DEFAULT_SCAN_INTERVAL_GROUP4),
            "default_config_counters_3": str(DEFAULT_SCAN_INTERVAL_GROUP5),
        }

        return self.async_show_form(
            step_id="init",
            data_schema=options_schema,
            errors=errors,
            description_placeholders=description_placeholders,
        )
