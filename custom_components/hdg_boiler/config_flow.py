"""
Configuration flow for the HDG Bavaria Boiler integration.

This module manages the user interaction for setting up the HDG Bavaria Boiler
integration. It handles the initial configuration step where the user provides
the boiler's host IP and an optional device alias. It also provides an options
flow for adjusting scan intervals, debug logging, and the source timezone post-setup.
"""

from __future__ import annotations

__version__ = "0.9.19"

import time
import logging
from typing import Any, Dict, Optional
import asyncio

import voluptuous as vol
from homeassistant import config_entries, core
from homeassistant.core import callback
from homeassistant.helpers.aiohttp_client import async_get_clientsession
import homeassistant.helpers.config_validation as cv

import async_timeout
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
    MIN_SCAN_INTERVAL,
    MAX_SCAN_INTERVAL,
    CONF_SOURCE_TIMEZONE,
    DEFAULT_SOURCE_TIMEZONE,
    CONFIG_FLOW_API_TIMEOUT,
)
from .polling_groups import HDG_NODE_PAYLOADS
from .utils import normalize_alias_for_comparison

_LOGGER = logging.getLogger(DOMAIN)

# Schema for the initial user setup step.
USER_DATA_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_HOST_IP): str,
        vol.Optional(CONF_DEVICE_ALIAS): str,
    }
)


def _create_options_schema(options: Optional[Dict[str, Any]] = None) -> vol.Schema:
    """
    Generate the schema for the options flow.

    Dynamically creates the `voluptuous` schema for the options flow UI.
    It populates form fields with existing option values if available,
    otherwise uses default values. This includes settings for scan intervals,
    debug logging, and the source timezone for datetime parsing.
    """
    options = options or {}
    return vol.Schema(
        {
            vol.Optional(
                CONF_SCAN_INTERVAL_GROUP1,
                default=options.get(CONF_SCAN_INTERVAL_GROUP1, DEFAULT_SCAN_INTERVAL_GROUP1),
            ): vol.All(
                cv.positive_int,
                vol.Range(
                    min=MIN_SCAN_INTERVAL,
                    max=MAX_SCAN_INTERVAL,
                    msg="scan_interval_invalid_range_min_max",
                ),
            ),
            vol.Optional(
                CONF_SCAN_INTERVAL_GROUP2,
                default=options.get(CONF_SCAN_INTERVAL_GROUP2, DEFAULT_SCAN_INTERVAL_GROUP2),
            ): vol.All(
                cv.positive_int,
                vol.Range(
                    min=MIN_SCAN_INTERVAL,
                    max=MAX_SCAN_INTERVAL,
                    msg="scan_interval_invalid_range_min_max",
                ),
            ),
            vol.Optional(
                CONF_SCAN_INTERVAL_GROUP3,
                default=options.get(CONF_SCAN_INTERVAL_GROUP3, DEFAULT_SCAN_INTERVAL_GROUP3),
            ): vol.All(
                cv.positive_int,
                vol.Range(
                    min=MIN_SCAN_INTERVAL,
                    max=MAX_SCAN_INTERVAL,
                    msg="scan_interval_invalid_range_min_max",
                ),
            ),
            vol.Optional(
                CONF_SCAN_INTERVAL_GROUP4,
                default=options.get(CONF_SCAN_INTERVAL_GROUP4, DEFAULT_SCAN_INTERVAL_GROUP4),
            ): vol.All(
                cv.positive_int,
                vol.Range(
                    min=MIN_SCAN_INTERVAL,
                    max=MAX_SCAN_INTERVAL,
                    msg="scan_interval_invalid_range_min_max",
                ),
            ),
            vol.Optional(
                CONF_SCAN_INTERVAL_GROUP5,
                default=options.get(CONF_SCAN_INTERVAL_GROUP5, DEFAULT_SCAN_INTERVAL_GROUP5),
            ): vol.All(
                cv.positive_int,
                vol.Range(
                    min=MIN_SCAN_INTERVAL,
                    max=MAX_SCAN_INTERVAL,
                    msg="scan_interval_invalid_range_min_max",
                ),
            ),
            vol.Optional(
                CONF_ENABLE_DEBUG_LOGGING,
                default=options.get(CONF_ENABLE_DEBUG_LOGGING, DEFAULT_ENABLE_DEBUG_LOGGING),
            ): cv.boolean,
            vol.Optional(
                CONF_SOURCE_TIMEZONE,
                default=options.get(CONF_SOURCE_TIMEZONE, DEFAULT_SOURCE_TIMEZONE),
            ): str,  # Text input for timezone string
        }
    )


async def validate_host_connectivity(hass: core.HomeAssistant, host_ip: str) -> bool:
    """
    Validate connectivity to the HDG boiler.

    Attempts a basic API call to the provided host IP to verify that the
    device is reachable and responds as an HDG boiler. This helps ensure
    correct configuration before proceeding with the setup.
    """
    start_time_validation = time.monotonic()
    from .api import (
        HdgApiClient,
        HdgApiError,
        HdgApiConnectionError,
    )

    _LOGGER.debug(f"validate_host_connectivity: Starting validation for host_ip: {host_ip}")
    session = async_get_clientsession(hass)  # Obtain a session for the API client
    # Create a temporary API client instance for this validation check using the obtained session.
    temp_api_client = HdgApiClient(session, host_ip)

    try:
        _LOGGER.debug(
            f"validate_host_connectivity: Attempting HdgApiClient.async_check_connectivity() to {host_ip} with timeout {CONFIG_FLOW_API_TIMEOUT}s"
        )
        start_time_check_connectivity = time.monotonic()
        async with async_timeout.timeout(CONFIG_FLOW_API_TIMEOUT):
            is_connected = await temp_api_client.async_check_connectivity()
        end_time_check_connectivity = time.monotonic()
        duration_check_connectivity = end_time_check_connectivity - start_time_check_connectivity
        _LOGGER.debug(
            f"validate_host_connectivity: HdgApiClient.async_check_connectivity() to {host_ip} "
            f"completed in {duration_check_connectivity:.2f}s. Result: {is_connected}"
        )

        if is_connected:
            _LOGGER.debug(f"validate_host_connectivity: Connectivity test to {host_ip} successful.")
            return True
        # `async_check_connectivity` returned False: host reached, but not an HDG boiler.
        _LOGGER.warning(
            f"validate_host_connectivity: Connectivity test to {host_ip} failed (HdgApiClient reported not connected)."
        )
        return False
    except asyncio.TimeoutError:
        # This catches the timeout from the new outer `async_timeout.timeout(CONFIG_FLOW_API_TIMEOUT)`
        _LOGGER.warning(
            f"validate_host_connectivity: Timeout after {CONFIG_FLOW_API_TIMEOUT}s connecting to host_ip {host_ip}."
        )
        return False
    except HdgApiConnectionError as e:
        # Specific error for network/connection issues (e.g., timeout, host down).
        _LOGGER.warning(
            f"validate_host_connectivity: HdgApiConnectionError (transient network issue?) for host_ip {host_ip}: {e}"
        )
        return False
    except HdgApiError as e:
        # Other API errors (e.g., unexpected response format).
        _LOGGER.warning(
            f"validate_host_connectivity: HdgApiError encountered for host_ip {host_ip}: {e}"
        )
        return False
    except Exception as e:
        # Catch any other unexpected exceptions during the validation.
        _LOGGER.error(
            f"validate_host_connectivity: Unexpected exception for host_ip {host_ip}: {e}",
            exc_info=True,
        )
        # Re-raise to ensure Home Assistant handles it as a setup failure.
        raise
    finally:
        end_time_validation = time.monotonic()
        duration_validation = end_time_validation - start_time_validation
        _LOGGER.debug(
            f"validate_host_connectivity: Finished validation for host_ip: {host_ip}. "
            f"Total duration: {duration_validation:.2f}s"
        )


class HdgBoilerConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handles the configuration flow for the HDG Bavaria Boiler integration."""

    VERSION = 1

    async def _async_validate_user_input(
        self, user_input: Dict[str, Any], current_entry_id: Optional[str] = None
    ) -> tuple[Optional[str], Optional[str], Dict[str, str]]:  # type: ignore[type-arg]
        """
        Validate the user-provided host IP and device alias.

        Ensures the host IP is provided. If a device alias is given, it checks
        that it's not solely whitespace. It also verifies that the (normalized)
        alias is unique among existing HDG Boiler integration entries, excluding
        the current entry if `current_entry_id` is supplied (e.g., during reconfigure).

        Returns:
            A tuple: (stripped_host_ip, stripped_device_alias, errors_dict).
        """

        errors: Dict[str, str] = {}
        host_ip = user_input.get(CONF_HOST_IP, "").strip()
        raw_device_alias = user_input.get(CONF_DEVICE_ALIAS, "")  # Keep raw for whitespace check
        device_alias = raw_device_alias.strip()

        if not host_ip:
            errors["base"] = "host_ip_required"
            return None, device_alias, errors

        if raw_device_alias and not device_alias:  # Alias was given but is only whitespace.
            errors[CONF_DEVICE_ALIAS] = "alias_is_whitespace"
            _LOGGER.warning(
                "Device alias provided consisted only of whitespace or invisible characters after normalization."
            )
        elif device_alias:  # Alias is non-empty; check for duplicates.
            existing_entries = self.hass.config_entries.async_entries(DOMAIN)
            for entry in existing_entries:
                if current_entry_id is not None and entry.entry_id == current_entry_id:
                    # Skip self-comparison if reconfiguring an existing entry.
                    continue
                # Use the utility function for normalization
                existing_alias_normalized = normalize_alias_for_comparison(
                    entry.data.get(CONF_DEVICE_ALIAS, "")
                )
                if existing_alias_normalized == normalize_alias_for_comparison(device_alias):
                    errors[CONF_DEVICE_ALIAS] = "alias_already_exists"
                    _LOGGER.warning(
                        f"Device alias '{device_alias}' is already in use by another entry."
                    )
                    break
        return host_ip, device_alias, errors

    async def async_step_user(self, user_input: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """Handle the initial user-initiated step of the configuration flow."""
        errors: Dict[str, str] = {}  # Initialize errors at the beginning
        current_host_ip = user_input.get(CONF_HOST_IP, "") if user_input else ""
        current_device_alias = user_input.get(CONF_DEVICE_ALIAS, "") if user_input else ""

        if user_input is not None:
            host_ip, device_alias, validation_errors = await self._async_validate_user_input(
                user_input, current_entry_id=None  # This is a new setup, so no current_entry_id.
            )
            errors |= validation_errors

            if not errors and host_ip:  # Proceed if initial validation passed and host_ip is valid.
                # Set unique ID based on host_ip to prevent duplicate configurations for the same device.
                await self.async_set_unique_id(host_ip.lower())
                # Abort if an entry with this unique ID (host_ip) already exists.
                self._abort_if_unique_id_configured()

                # Validate connectivity to the boiler.
                is_connected = await validate_host_connectivity(self.hass, host_ip)
                if is_connected:
                    # Prepare configuration data for the new entry.
                    config_data: Dict[str, Any] = {
                        CONF_HOST_IP: host_ip,
                        CONF_DEVICE_ALIAS: device_alias,
                        CONF_SCAN_INTERVAL_GROUP1: DEFAULT_SCAN_INTERVAL_GROUP1,
                        CONF_SCAN_INTERVAL_GROUP2: DEFAULT_SCAN_INTERVAL_GROUP2,
                        CONF_SCAN_INTERVAL_GROUP3: DEFAULT_SCAN_INTERVAL_GROUP3,
                        CONF_SCAN_INTERVAL_GROUP4: DEFAULT_SCAN_INTERVAL_GROUP4,
                        CONF_SCAN_INTERVAL_GROUP5: DEFAULT_SCAN_INTERVAL_GROUP5,
                        CONF_ENABLE_DEBUG_LOGGING: DEFAULT_ENABLE_DEBUG_LOGGING,
                        CONF_SOURCE_TIMEZONE: DEFAULT_SOURCE_TIMEZONE,
                    }

                    # Create the config entry. Title uses alias or host_ip for display in HA.
                    return self.async_create_entry(
                        title=f"{DEFAULT_NAME} ({device_alias or host_ip})",
                        data=config_data,
                    )
                else:
                    errors["base"] = "cannot_connect"

        data_schema = vol.Schema(
            {
                vol.Required(CONF_HOST_IP, default=current_host_ip): str,
                vol.Optional(CONF_DEVICE_ALIAS, default=current_device_alias): str,
            }
        )
        return self.async_show_form(step_id="user", data_schema=data_schema, errors=errors)

    @staticmethod
    @callback
    def async_get_options_flow(
        config_entry: config_entries.ConfigEntry,
    ) -> config_entries.OptionsFlow:
        """
        Get the options flow handler for this integration.

        Home Assistant calls this to obtain an instance of the options flow handler,
        which is then managed by `OptionsFlowManager`.
        """
        return HdgBoilerOptionsFlowHandler(config_entry)


class HdgBoilerOptionsFlowHandler(config_entries.OptionsFlow):
    """Handles the options flow for the HDG Bavaria Boiler integration."""

    def _get_description_placeholders(self) -> Dict[str, str]:
        """Return placeholders for the options form description."""
        return {
            "default_realtime_core": str(
                HDG_NODE_PAYLOADS["group1_realtime_core"]["default_scan_interval"]
            ),
            "default_status_general": str(
                HDG_NODE_PAYLOADS["group2_status_general"]["default_scan_interval"]
            ),
            "default_config_counters_1": str(
                HDG_NODE_PAYLOADS["group3_config_counters_1"]["default_scan_interval"]
            ),
            "default_config_counters_2": str(
                HDG_NODE_PAYLOADS["group4_config_counters_2"]["default_scan_interval"]
            ),
            "default_config_counters_3": str(
                HDG_NODE_PAYLOADS["group5_config_counters_3"]["default_scan_interval"]
            ),
        }

    async def async_step_init(self, user_input: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """Manage options for scan intervals and debug logging."""
        current_errors: Dict[str, str] = {}

        if user_input is not None:
            # Validate timezone string if provided
            source_timezone_input = user_input.get(CONF_SOURCE_TIMEZONE, DEFAULT_SOURCE_TIMEZONE)
            try:
                from zoneinfo import ZoneInfo, ZoneInfoNotFoundError  # Local import for validation

                ZoneInfo(source_timezone_input)  # Attempt to create ZoneInfo object
            except ZoneInfoNotFoundError:
                current_errors[CONF_SOURCE_TIMEZONE] = "invalid_timezone"
                _LOGGER.error(
                    f"Invalid timezone string provided in options: {source_timezone_input}"
                )
            except Exception as e:  # Catch other unexpected errors during ZoneInfo creation
                current_errors[CONF_SOURCE_TIMEZONE] = (
                    "invalid_timezone_generic"  # Keep generic error key for translation
                )
                _LOGGER.error(
                    f"Unexpected error validating timezone string '{source_timezone_input}': {e}",
                    exc_info=True,
                )

            # If user_input is provided, HA has already validated it against the schema
            # from the previous async_show_form call. If there were schema errors,
            # Home Assistant re-calls this method, and `self.async_show_form` below
            # will automatically display those errors.
            # We only need to explicitly handle `current_errors` if we add custom,
            # non-schema-based validation here.
            if not current_errors:  # No custom errors added in this step.
                _LOGGER.debug(f"Updating options for {self.config_entry.title}: {user_input}")
                return self.async_create_entry(title="", data=user_input)
            else:
                # This block would be hit if `current_errors` was populated by custom validation.
                options_schema_with_errors = _create_options_schema(user_input)
                return self.async_show_form(
                    step_id="init",
                    data_schema=options_schema_with_errors,
                    errors=current_errors,
                    description_placeholders=self._get_description_placeholders(),
                )

        options_schema = _create_options_schema(self.config_entry.options)

        return self.async_show_form(
            step_id="init",
            data_schema=options_schema,
            errors=current_errors,
            description_placeholders=self._get_description_placeholders(),
        )
