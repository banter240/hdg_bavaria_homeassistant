"""Configuration flow for the HDG Bavaria Boiler integration."""

from __future__ import annotations

__version__ = "0.9.35"

import logging
from typing import Any
from urllib.parse import urlparse

import async_timeout
import voluptuous as vol
from homeassistant import config_entries, core
from homeassistant.core import callback
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from voluptuous.schema_builder import Marker
from homeassistant.helpers.selector import (
    BooleanSelector,
    NumberSelector,
    NumberSelectorMode,
    SelectSelector,
    SelectSelectorConfig,
    SelectSelectorMode,
    TextSelector,
)

from .api import (
    HdgApiClient,
    HdgApiConnectionError,
    HdgApiError,
)
from .const import (
    CONF_DEVICE_ALIAS,
    CONF_ADVANCED_LOGGING,
    CONF_HOST_IP,
    CONF_SOURCE_TIMEZONE,
    CONF_API_TIMEOUT,
    CONFIG_FLOW_API_TIMEOUT,
    CONFIG_FLOW_TEST_PAYLOAD,
    DEFAULT_SOURCE_TIMEZONE,
    DEFAULT_API_TIMEOUT,
    MIN_API_TIMEOUT,
    MAX_API_TIMEOUT,
    CONF_POLLING_PREEMPTION_TIMEOUT,
    DEFAULT_POLLING_PREEMPTION_TIMEOUT,
    CONF_CONNECT_TIMEOUT,
    DEFAULT_CONNECT_TIMEOUT,
    MIN_CONNECT_TIMEOUT,
    MAX_CONNECT_TIMEOUT,
    MIN_POLLING_PREEMPTION_TIMEOUT,
    MAX_POLLING_PREEMPTION_TIMEOUT,
    CONF_RECENTLY_SET_POLL_IGNORE_WINDOW_S,
    DEFAULT_RECENTLY_SET_POLL_IGNORE_WINDOW_S,
    MIN_RECENTLY_SET_POLL_IGNORE_WINDOW_S,
    MAX_RECENTLY_SET_POLL_IGNORE_WINDOW_S,
    CONF_LOG_LEVEL_THRESHOLD_FOR_CONNECTION_ERRORS,
    DEFAULT_LOG_LEVEL_THRESHOLD_FOR_CONNECTION_ERRORS,
    MAX_LOG_LEVEL_THRESHOLD_FOR_CONNECTION_ERRORS,
    DOMAIN,
    MAX_SCAN_INTERVAL,
    DEFAULT_ADVANCED_LOGGING,
    MIN_SCAN_INTERVAL,
    CONF_LOG_LEVEL,
    DEFAULT_LOG_LEVEL,
    LOG_LEVELS,
    MIN_LOG_LEVEL_THRESHOLD_FOR_CONNECTION_ERRORS,
    POLLING_GROUP_DEFINITIONS,
    LIFECYCLE_LOGGER_NAME,
    ENTITY_DETAIL_LOGGER_NAME,
)
from .helpers.network_utils import async_execute_icmp_ping, prepare_base_url


_LOGGER = logging.getLogger(DOMAIN)
_LIFECYCLE_LOGGER = logging.getLogger(LIFECYCLE_LOGGER_NAME)
_ENTITY_DETAIL_LOGGER = logging.getLogger(ENTITY_DETAIL_LOGGER_NAME)


async def _validate_host_connectivity(hass: core.HomeAssistant, host_ip: str) -> bool:
    """Validate connectivity to the HDG boiler."""
    try:
        prepared_base_url = prepare_base_url(host_ip)
        if not prepared_base_url:
            _LOGGER.warning(
                f"Invalid host_ip format '{host_ip}'. Could not prepare base URL."
            )
            return False
        parsed_url = urlparse(prepared_base_url)
        host_to_ping = parsed_url.hostname
    except Exception as e:
        _LOGGER.warning(f"Unexpected error parsing host_ip '{host_ip}': {e}")
        return False

    if not host_to_ping:
        _LOGGER.error(
            f"Could not extract hostname from host_ip '{host_ip}' for ICMP ping."
        )
        return False

    if not await async_execute_icmp_ping(host_to_ping, timeout_seconds=3):
        _LOGGER.warning(f"ICMP ping to {host_to_ping} (from IP: {host_ip}) failed.")
        return False
    _ENTITY_DETAIL_LOGGER.debug(
        f"ICMP ping to {host_to_ping} (from IP: {host_ip}) successful."
    )

    session = async_get_clientsession(hass)
    temp_api_client = HdgApiClient(
        session,
        host_ip,
        CONFIG_FLOW_API_TIMEOUT,
        DEFAULT_CONNECT_TIMEOUT,
    )

    try:
        async with async_timeout.timeout(CONFIG_FLOW_API_TIMEOUT):
            test_payload_str = CONFIG_FLOW_TEST_PAYLOAD
            _ENTITY_DETAIL_LOGGER.debug(
                f"Attempting to fetch test nodes ({test_payload_str}) from {host_ip}"
            )
            test_data = await temp_api_client.async_get_nodes_data(test_payload_str)

            if test_data and isinstance(test_data, list) and len(test_data) >= 1:
                _ENTITY_DETAIL_LOGGER.debug(
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
        _LOGGER.warning("API error during HDG device check for %s: %s", host_ip, err)
    except TimeoutError:
        _LOGGER.warning("Timeout during HDG device check for %s.", host_ip)
    except Exception as err:
        _LOGGER.exception(
            "Unexpected error during HDG device check for %s: %s", host_ip, err
        )
    return False


@config_entries.HANDLERS.register(DOMAIN)
class HdgBoilerConfigFlow(config_entries.ConfigFlow):
    """Handle a config flow for HDG Bavaria Boiler."""

    USER_DATA_SCHEMA = vol.Schema(
        {
            vol.Required(CONF_HOST_IP): TextSelector(),
            vol.Optional(CONF_DEVICE_ALIAS, default=""): TextSelector(),
        }
    )

    @staticmethod
    def _create_options_schema(
        options: config_entries.Mapping[str, Any] | None = None,
    ) -> vol.Schema:
        """Generate the dynamic schema for the options flow.

        This static method builds the voluptuous schema for the options form,
        dynamically adding fields for each polling group defined in `const.py`.
        This approach centralizes schema definition and adheres to the DRY principle,
        allowing the `HdgBoilerOptionsFlowHandler` to reuse this logic.
        """
        current_options = options or {}
        options_schema_dict: dict[Marker, Any] = {}

        for group_def in POLLING_GROUP_DEFINITIONS:
            group_key = group_def["key"]
            config_key = f"scan_interval_{group_key}"

            default_interval = group_def["default_interval"]

            options_schema_dict[
                vol.Optional(
                    config_key,
                    default=current_options.get(config_key, default_interval),
                )
            ] = NumberSelector(
                {
                    "min": MIN_SCAN_INTERVAL,
                    "max": MAX_SCAN_INTERVAL,
                    "step": 1,
                    "mode": NumberSelectorMode.BOX,
                    "unit_of_measurement": "s",
                }
            )

        options_schema_dict |= {
            vol.Required(
                CONF_LOG_LEVEL,
                default=current_options.get(CONF_LOG_LEVEL, DEFAULT_LOG_LEVEL),
            ): SelectSelector(
                SelectSelectorConfig(
                    options=LOG_LEVELS, mode=SelectSelectorMode.DROPDOWN
                )
            ),
            vol.Optional(
                CONF_ADVANCED_LOGGING,
                default=current_options.get(
                    CONF_ADVANCED_LOGGING, DEFAULT_ADVANCED_LOGGING
                ),
            ): BooleanSelector(),
            vol.Optional(
                CONF_SOURCE_TIMEZONE,
                default=current_options.get(
                    CONF_SOURCE_TIMEZONE, DEFAULT_SOURCE_TIMEZONE
                ),
            ): TextSelector(),
            vol.Optional(
                CONF_API_TIMEOUT,
                default=current_options.get(CONF_API_TIMEOUT, DEFAULT_API_TIMEOUT),
            ): NumberSelector(
                {
                    "min": MIN_API_TIMEOUT,
                    "max": MAX_API_TIMEOUT,
                    "step": 1,
                    "mode": NumberSelectorMode.BOX,
                    "unit_of_measurement": "s",
                }
            ),
            vol.Optional(
                CONF_CONNECT_TIMEOUT,
                default=current_options.get(
                    CONF_CONNECT_TIMEOUT, DEFAULT_CONNECT_TIMEOUT
                ),
            ): NumberSelector(
                {
                    "min": MIN_CONNECT_TIMEOUT,
                    "max": MAX_CONNECT_TIMEOUT,
                    "step": 0.1,
                    "mode": NumberSelectorMode.BOX,
                    "unit_of_measurement": "s",
                }
            ),
            vol.Optional(
                CONF_POLLING_PREEMPTION_TIMEOUT,
                default=current_options.get(
                    CONF_POLLING_PREEMPTION_TIMEOUT,
                    DEFAULT_POLLING_PREEMPTION_TIMEOUT,
                ),
            ): NumberSelector(
                {
                    "min": MIN_POLLING_PREEMPTION_TIMEOUT,
                    "max": MAX_POLLING_PREEMPTION_TIMEOUT,
                    "step": 0.1,
                    "mode": NumberSelectorMode.BOX,
                    "unit_of_measurement": "s",
                }
            ),
            vol.Optional(
                CONF_LOG_LEVEL_THRESHOLD_FOR_CONNECTION_ERRORS,
                default=current_options.get(
                    CONF_LOG_LEVEL_THRESHOLD_FOR_CONNECTION_ERRORS,
                    DEFAULT_LOG_LEVEL_THRESHOLD_FOR_CONNECTION_ERRORS,
                ),
            ): NumberSelector(
                {
                    "min": MIN_LOG_LEVEL_THRESHOLD_FOR_CONNECTION_ERRORS,
                    "max": MAX_LOG_LEVEL_THRESHOLD_FOR_CONNECTION_ERRORS,
                    "step": 1,
                    "mode": NumberSelectorMode.BOX,
                    "unit_of_measurement": "",
                }
            ),
            vol.Optional(
                CONF_RECENTLY_SET_POLL_IGNORE_WINDOW_S,
                default=current_options.get(
                    CONF_RECENTLY_SET_POLL_IGNORE_WINDOW_S,
                    DEFAULT_RECENTLY_SET_POLL_IGNORE_WINDOW_S,
                ),
            ): NumberSelector(
                {
                    "min": MIN_RECENTLY_SET_POLL_IGNORE_WINDOW_S,
                    "max": MAX_RECENTLY_SET_POLL_IGNORE_WINDOW_S,
                    "step": 0.5,
                    "mode": NumberSelectorMode.BOX,
                    "unit_of_measurement": "s",
                }
            ),
        }
        return vol.Schema(options_schema_dict)

    @staticmethod
    def _get_description_placeholders(step_id: str) -> dict[str, str]:
        """Return placeholders for the form description text.

        This method provides dynamic values that can be inserted into the
        description fields of the configuration or options form, such as
        min/max values for validation or default scan intervals.
        """
        placeholders: dict[str, str] = {}
        if step_id == "options_init":
            placeholders = {
                "min_scan_interval": str(MIN_SCAN_INTERVAL),
                "max_scan_interval": str(MAX_SCAN_INTERVAL),
                "min_api_timeout": str(MIN_API_TIMEOUT),
                "max_api_timeout": str(MAX_API_TIMEOUT),
                "min_polling_preemption_timeout": str(MIN_POLLING_PREEMPTION_TIMEOUT),
                "max_polling_preemption_timeout": str(MAX_POLLING_PREEMPTION_TIMEOUT),
                "min_log_level_threshold": str(
                    MIN_LOG_LEVEL_THRESHOLD_FOR_CONNECTION_ERRORS
                ),
                "max_log_level_threshold": str(
                    MAX_LOG_LEVEL_THRESHOLD_FOR_CONNECTION_ERRORS
                ),
                "min_ignore_window": str(MIN_RECENTLY_SET_POLL_IGNORE_WINDOW_S),
                "max_ignore_window": str(MAX_RECENTLY_SET_POLL_IGNORE_WINDOW_S),
                "default_ignore_window": str(DEFAULT_RECENTLY_SET_POLL_IGNORE_WINDOW_S),
            }
            # Dynamically create placeholders for default scan intervals
            for group_def in POLLING_GROUP_DEFINITIONS:
                group_key = group_def["key"]
                # Dynamically generate config_key, consistent with polling_group_manager.py
                config_key = f"scan_interval_{group_key}"
                placeholder_key = f"default_{config_key}"  # Use dynamically generated config_key for placeholder name
                placeholders[placeholder_key] = str(group_def["default_interval"])
        return placeholders

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
                is_hdg_device_and_connected = await _validate_host_connectivity(
                    self.hass, host_ip
                )
                if is_hdg_device_and_connected:
                    _LIFECYCLE_LOGGER.info(
                        f"Successfully validated HDG device at {host_ip}."
                    )
                    await self.async_set_unique_id(host_ip.lower())
                    self._abort_if_unique_id_configured()

                    _LIFECYCLE_LOGGER.debug("Creating entry for host_ip: %s", host_ip)
                    return self.async_create_entry(
                        title=current_device_alias or f"HDG Boiler ({host_ip})",
                        data=user_input,
                    )
                else:
                    _LOGGER.warning(
                        f"Validation failed for host {host_ip}. It's either not reachable or not a recognized HDG device."
                    )
                    errors["base"] = "cannot_connect"
        data_schema_user = self.USER_DATA_SCHEMA
        if user_input:
            data_schema_user = vol.Schema(
                {
                    vol.Required(
                        CONF_HOST_IP, default=user_input.get(CONF_HOST_IP, "")
                    ): TextSelector(),
                    vol.Optional(
                        CONF_DEVICE_ALIAS,
                        default=user_input.get(CONF_DEVICE_ALIAS, ""),
                    ): TextSelector(),
                }
            )

        return self.async_show_form(
            step_id="user",
            data_schema=data_schema_user,
            errors=errors,
            description_placeholders=self._get_description_placeholders("user"),
        )

    @staticmethod
    @callback
    def async_get_options_flow(
        config_entry: config_entries.ConfigEntry,
    ) -> HdgBoilerOptionsFlowHandler:
        """Get the options flow for this handler, as required by Home Assistant."""
        _LIFECYCLE_LOGGER.debug(
            "async_get_options_flow called for entry: %s", config_entry.entry_id
        )
        return HdgBoilerOptionsFlowHandler(config_entry)


class HdgBoilerOptionsFlowHandler(config_entries.OptionsFlow):
    """Handle an options flow for HDG Bavaria Boiler."""

    def __init__(self, config_entry: config_entries.ConfigEntry) -> None:
        """Initialize options flow."""
        super().__init__()
        _LOGGER.debug(
            "HdgBoilerOptionsFlowHandler initialized for entry: %s",
            config_entry.entry_id,
        )

    def _get_options_schema(self) -> vol.Schema:
        """Get the options schema.

        This creates a temporary instance of the main config flow to reuse its schema creation logic.
        This is a workaround; a more robust solution might involve static methods or duplicated logic.
        """
        return HdgBoilerConfigFlow._create_options_schema(self.config_entry.options)

    def _get_options_description_placeholders(self) -> dict[str, str]:
        """Get description placeholders for the options form.

        Similar to _get_options_schema, it reuses logic from the main config flow.
        """
        return HdgBoilerConfigFlow._get_description_placeholders("options_init")

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.ConfigFlowResult:
        """Manage minimal options."""
        _LIFECYCLE_LOGGER.debug(
            "OptionsFlow async_step_init called with user_input: %s", user_input
        )
        current_errors: dict[str, str] = {}

        if user_input is not None:
            # Options are directly saved without further validation in this simple flow.
            _LIFECYCLE_LOGGER.debug(
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
