"""Configuration flow for the HDG Bavaria Boiler integration."""

from __future__ import annotations

__version__ = "0.3.2"
__all__ = ["HdgBoilerConfigFlow"]

from typing import Any, TypedDict
from urllib.parse import urlparse

import voluptuous as vol
from homeassistant import config_entries, core
from homeassistant.const import CONF_SCAN_INTERVAL
from homeassistant.core import callback
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.selector import (
    BooleanSelector,
    NumberSelector,
    NumberSelectorConfig,
    NumberSelectorMode,
    SelectSelector,
    SelectSelectorConfig,
    SelectSelectorMode,
    TextSelector,
)

from .api import HdgApiClient, HdgApiConnectionError, HdgApiError
from .const import (
    CONF_ADVANCED_LOGGING,
    CONF_API_TIMEOUT,
    CONF_CONNECT_TIMEOUT,
    CONF_DEVICE_ALIAS,
    CONF_ERROR_THRESHOLD,
    CONF_HOST_IP,
    CONF_LOG_LEVEL,
    CONF_LOG_LEVEL_THRESHOLD_FOR_CONNECTION_ERRORS,
    CONF_LOG_LEVEL_THRESHOLD_FOR_PREEMPTION_ERRORS,
    CONF_POLLING_PREEMPTION_TIMEOUT,
    CONF_RECENTLY_SET_POLL_IGNORE_WINDOW_S,
    CONF_SOURCE_TIMEZONE,
    CONFIG_FLOW_API_TIMEOUT,
    CONFIG_FLOW_TEST_PAYLOAD,
    DEFAULT_ADVANCED_LOGGING,
    DEFAULT_API_TIMEOUT,
    DEFAULT_CONNECT_TIMEOUT,
    DEFAULT_ERROR_THRESHOLD,
    DEFAULT_LOG_LEVEL,
    DEFAULT_LOG_LEVEL_THRESHOLD_FOR_CONNECTION_ERRORS,
    DEFAULT_LOG_LEVEL_THRESHOLD_FOR_PREEMPTION_ERRORS,
    DEFAULT_POLLING_PREEMPTION_TIMEOUT,
    DEFAULT_RECENTLY_SET_POLL_IGNORE_WINDOW_S,
    DEFAULT_SOURCE_TIMEZONE,
    DOMAIN,
    LOG_LEVELS,
    MAX_API_TIMEOUT,
    MAX_CONNECT_TIMEOUT,
    MAX_ERROR_THRESHOLD,
    MAX_LOG_LEVEL_THRESHOLD_FOR_CONNECTION_ERRORS,
    MAX_LOG_LEVEL_THRESHOLD_FOR_PREEMPTION_ERRORS,
    MAX_POLLING_PREEMPTION_TIMEOUT,
    MAX_RECENTLY_SET_POLL_IGNORE_WINDOW_S,
    MAX_SCAN_INTERVAL,
    MIN_API_TIMEOUT,
    MIN_CONNECT_TIMEOUT,
    MIN_ERROR_THRESHOLD,
    MIN_LOG_LEVEL_THRESHOLD_FOR_CONNECTION_ERRORS,
    MIN_LOG_LEVEL_THRESHOLD_FOR_PREEMPTION_ERRORS,
    MIN_POLLING_PREEMPTION_TIMEOUT,
    MIN_RECENTLY_SET_POLL_IGNORE_WINDOW_S,
    MIN_SCAN_INTERVAL,
    POLLING_GROUP_DEFINITIONS,
)
from .helpers.logging_utils import _LOGGER
from .helpers.network_utils import async_execute_icmp_ping, prepare_base_url


class NumberSelectorConfigDict(TypedDict, total=False):
    """TypedDict for NumberSelector configuration."""

    min: float
    max: float
    step: float
    mode: NumberSelectorMode
    unit_of_measurement: str


async def _get_hostname_from_host_ip(host_ip: str) -> str | None:
    """Prepare the URL and extract the hostname."""
    prepared_url = prepare_base_url(host_ip)
    if not prepared_url or not (hostname := urlparse(prepared_url).hostname):
        _LOGGER.warning("Invalid host_ip format: '%s'", host_ip)
        return None
    return hostname


async def _test_api_connectivity(hass: core.HomeAssistant, host_ip: str) -> bool:
    """Test the API connectivity to the HDG boiler."""
    session = async_get_clientsession(hass)
    api_client = HdgApiClient(
        session, host_ip, CONFIG_FLOW_API_TIMEOUT, DEFAULT_CONNECT_TIMEOUT
    )
    test_data = await api_client.async_get_nodes_data(CONFIG_FLOW_TEST_PAYLOAD)

    if test_data and isinstance(test_data, list):
        _LOGGER.debug("Successfully fetched test nodes from %s.", host_ip)
        return True

    _LOGGER.warning("Failed to fetch test nodes from %s.", host_ip)
    return False


async def _validate_host_connectivity(hass: core.HomeAssistant, host_ip: str) -> bool:
    """Validate connectivity to the HDG boiler."""
    try:
        hostname = await _get_hostname_from_host_ip(host_ip)
        if not hostname:
            return False

        if not await async_execute_icmp_ping(hostname, timeout=3):
            _LOGGER.warning("ICMP ping to %s (from %s) failed.", hostname, host_ip)
            return False

        return await _test_api_connectivity(hass, host_ip)

    except (HdgApiConnectionError, HdgApiError) as err:
        _LOGGER.warning("API error during device check for %s: %s", host_ip, err)
    except Exception:
        _LOGGER.exception("Unexpected error during device check for %s", host_ip)
    return False


@config_entries.HANDLERS.register(DOMAIN)
class HdgBoilerConfigFlow(config_entries.ConfigFlow):
    """Handle a config flow for HDG Bavaria Boiler."""

    VERSION = 1

    @staticmethod
    @callback
    def async_get_options_flow(
        config_entry: config_entries.ConfigEntry,
    ) -> HdgBoilerOptionsFlowHandler:
        """Get the options flow for this handler."""
        return HdgBoilerOptionsFlowHandler(config_entry)

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.ConfigFlowResult:
        """Handle the initial user step."""
        errors: dict[str, str] = {}
        if user_input is not None:
            host_ip = user_input[CONF_HOST_IP]
            if await _validate_host_connectivity(self.hass, host_ip):
                await self.async_set_unique_id(host_ip.lower())
                self._abort_if_unique_id_configured()
                title = user_input.get(CONF_DEVICE_ALIAS) or f"HDG Boiler ({host_ip})"
                return self.async_create_entry(title=title, data=user_input)
            errors["base"] = "cannot_connect"

        data_schema = vol.Schema(
            {
                vol.Required(CONF_HOST_IP): TextSelector(),
                vol.Optional(CONF_DEVICE_ALIAS): TextSelector(),
            }
        )
        return self.async_show_form(
            step_id="user", data_schema=data_schema, errors=errors
        )


class HdgBoilerOptionsFlowHandler(config_entries.OptionsFlow):
    """Handle an options flow for HDG Bavaria Boiler."""

    def __init__(self, config_entry: config_entries.ConfigEntry) -> None:
        """Initialize options flow."""

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.ConfigFlowResult:
        """Manage the options."""
        if user_input is not None:
            return self.async_create_entry(title="", data=user_input)

        return self.async_show_form(
            step_id="init",
            data_schema=self._get_options_schema(),
            description_placeholders=self._get_description_placeholders(),
        )

    def _get_options_schema(self) -> vol.Schema:
        """Generate the dynamic schema for the options flow."""
        options = self.config_entry.options
        schema: dict[vol.Marker, Any] = {}

        # Polling intervals
        for group in POLLING_GROUP_DEFINITIONS:
            key = f"{CONF_SCAN_INTERVAL}_{group['key']}"
            schema[
                vol.Optional(key, default=options.get(key, group["default_interval"]))
            ] = NumberSelector(
                NumberSelectorConfig(
                    min=MIN_SCAN_INTERVAL,
                    max=MAX_SCAN_INTERVAL,
                    step=1,
                    mode=NumberSelectorMode.BOX,
                    unit_of_measurement="s",
                )
            )

        # Other selectors
        schema_definitions = [
            (
                CONF_LOG_LEVEL,
                SelectSelector(
                    SelectSelectorConfig(
                        options=LOG_LEVELS, mode=SelectSelectorMode.DROPDOWN
                    )
                ),
                DEFAULT_LOG_LEVEL,
                vol.Required,
            ),
            (
                CONF_ADVANCED_LOGGING,
                BooleanSelector(),
                DEFAULT_ADVANCED_LOGGING,
                vol.Optional,
            ),
            (
                CONF_SOURCE_TIMEZONE,
                TextSelector(),
                DEFAULT_SOURCE_TIMEZONE,
                vol.Optional,
            ),
        ]

        for key, selector, default, marker in schema_definitions:
            schema[marker(key, default=options.get(key, default))] = selector

        # Number selectors
        number_schema_definitions: list[
            tuple[str, float | int, NumberSelectorConfigDict]
        ] = [
            (
                CONF_API_TIMEOUT,
                DEFAULT_API_TIMEOUT,
                {
                    "min": MIN_API_TIMEOUT,
                    "max": MAX_API_TIMEOUT,
                    "step": 1,
                    "unit_of_measurement": "s",
                },
            ),
            (
                CONF_CONNECT_TIMEOUT,
                DEFAULT_CONNECT_TIMEOUT,
                {
                    "min": MIN_CONNECT_TIMEOUT,
                    "max": MAX_CONNECT_TIMEOUT,
                    "step": 0.1,
                    "unit_of_measurement": "s",
                },
            ),
            (
                CONF_POLLING_PREEMPTION_TIMEOUT,
                DEFAULT_POLLING_PREEMPTION_TIMEOUT,
                {
                    "min": MIN_POLLING_PREEMPTION_TIMEOUT,
                    "max": MAX_POLLING_PREEMPTION_TIMEOUT,
                    "step": 1,
                    "unit_of_measurement": "s",
                },
            ),
            (
                CONF_LOG_LEVEL_THRESHOLD_FOR_CONNECTION_ERRORS,
                DEFAULT_LOG_LEVEL_THRESHOLD_FOR_CONNECTION_ERRORS,
                {
                    "min": MIN_LOG_LEVEL_THRESHOLD_FOR_CONNECTION_ERRORS,
                    "max": MAX_LOG_LEVEL_THRESHOLD_FOR_CONNECTION_ERRORS,
                    "step": 1,
                },
            ),
            (
                CONF_ERROR_THRESHOLD,
                DEFAULT_ERROR_THRESHOLD,
                {
                    "min": MIN_ERROR_THRESHOLD,
                    "max": MAX_ERROR_THRESHOLD,
                    "step": 1,
                },
            ),
            (
                CONF_LOG_LEVEL_THRESHOLD_FOR_PREEMPTION_ERRORS,
                DEFAULT_LOG_LEVEL_THRESHOLD_FOR_PREEMPTION_ERRORS,
                {
                    "min": MIN_LOG_LEVEL_THRESHOLD_FOR_PREEMPTION_ERRORS,
                    "max": MAX_LOG_LEVEL_THRESHOLD_FOR_PREEMPTION_ERRORS,
                    "step": 1,
                },
            ),
            (
                CONF_RECENTLY_SET_POLL_IGNORE_WINDOW_S,
                DEFAULT_RECENTLY_SET_POLL_IGNORE_WINDOW_S,
                {
                    "min": MIN_RECENTLY_SET_POLL_IGNORE_WINDOW_S,
                    "max": MAX_RECENTLY_SET_POLL_IGNORE_WINDOW_S,
                    "step": 1,
                    "unit_of_measurement": "s",
                },
            ),
        ]

        for key, default, config in number_schema_definitions:
            config["mode"] = NumberSelectorMode.BOX
            schema[vol.Optional(key, default=options.get(key, default))] = (
                NumberSelector(NumberSelectorConfig(**config))
            )

        return vol.Schema(schema)

    def _get_description_placeholders(self) -> dict[str, str]:
        """Generate placeholders for the options flow description."""
        placeholders_map = {
            "min_scan_interval": MIN_SCAN_INTERVAL,
            "max_scan_interval": MAX_SCAN_INTERVAL,
            "min_api_timeout": MIN_API_TIMEOUT,
            "max_api_timeout": MAX_API_TIMEOUT,
            "min_connect_timeout": MIN_CONNECT_TIMEOUT,
            "max_connect_timeout": MAX_CONNECT_TIMEOUT,
            "min_polling_preemption_timeout": MIN_POLLING_PREEMPTION_TIMEOUT,
            "max_polling_preemption_timeout": MAX_POLLING_PREEMPTION_TIMEOUT,
            "min_log_level_threshold": MIN_LOG_LEVEL_THRESHOLD_FOR_CONNECTION_ERRORS,
            "max_log_level_threshold": MAX_LOG_LEVEL_THRESHOLD_FOR_CONNECTION_ERRORS,
            "min_error_threshold": MIN_ERROR_THRESHOLD,
            "max_error_threshold": MAX_ERROR_THRESHOLD,
            "min_preemption_threshold": MIN_LOG_LEVEL_THRESHOLD_FOR_PREEMPTION_ERRORS,
            "max_preemption_threshold": MAX_LOG_LEVEL_THRESHOLD_FOR_PREEMPTION_ERRORS,
            "min_ignore_window": MIN_RECENTLY_SET_POLL_IGNORE_WINDOW_S,
            "max_ignore_window": MAX_RECENTLY_SET_POLL_IGNORE_WINDOW_S,
            "default_ignore_window": DEFAULT_RECENTLY_SET_POLL_IGNORE_WINDOW_S,
        }
        placeholders = {k: str(v) for k, v in placeholders_map.items()}

        for group in POLLING_GROUP_DEFINITIONS:
            placeholders[f"default_scan_interval_{group['key']}"] = str(
                group["default_interval"]
            )
        return placeholders
