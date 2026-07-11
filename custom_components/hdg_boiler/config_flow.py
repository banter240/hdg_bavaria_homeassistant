"""Configuration flow for the HDG Bavaria Boiler integration."""

from __future__ import annotations

__all__ = ["HdgBoilerConfigFlow"]

from typing import Any, cast
from urllib.parse import urlparse

import voluptuous as vol
from homeassistant import config_entries, core, data_entry_flow
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
    CONF_ENABLE_EXT_WQ,
    CONF_ENABLE_HK2,
    CONF_ENABLE_HK3,
    CONF_ENABLE_HK4,
    CONF_ENABLE_HK5,
    CONF_ENABLE_HK6,
    CONF_ENABLE_LAGER,
    CONF_ENABLE_NETZPUMPE_1,
    CONF_ENABLE_NETZPUMPE_2,
    CONF_ENABLE_NETZPUMPE_3,
    CONF_ENABLE_PUFFER_2,
    CONF_ENABLE_SOLAR,
    CONF_ENABLE_WW1,
    CONF_ENABLE_WW2,
    CONF_ERROR_THRESHOLD,
    CONF_PUFFER_MITTE_OBEN_NODE_ID,
    CONF_PUFFER_MITTE_UNTEN_NODE_ID,
    CONF_FALLBACK_PING_INTERVAL,
    CONF_HOST_IP,
    CONF_LOG_LEVEL,
    CONF_LOG_LEVEL_THRESHOLD_FOR_CONNECTION_ERRORS,
    CONF_LOG_VERSION_PREFIX,
    CONF_LOG_LEVEL_THRESHOLD_FOR_PREEMPTION_ERRORS,
    CONF_POLLING_PREEMPTION_TIMEOUT,
    CONF_RECENTLY_SET_POLL_IGNORE_WINDOW_S,
    CONF_SOURCE_TIMEZONE,
    CONFIG_FLOW_API_TIMEOUT,
    CONFIG_FLOW_TEST_PAYLOAD,
    DEFAULT_ADVANCED_LOGGING,
    DEFAULT_API_TIMEOUT,
    DEFAULT_CONNECT_TIMEOUT,
    DEFAULT_ENABLE_EXT_WQ,
    DEFAULT_ENABLE_HK2,
    DEFAULT_ENABLE_HK3,
    DEFAULT_ENABLE_HK4,
    DEFAULT_ENABLE_HK5,
    DEFAULT_ENABLE_HK6,
    DEFAULT_ENABLE_LAGER,
    DEFAULT_ENABLE_NETZPUMPE_1,
    DEFAULT_ENABLE_NETZPUMPE_2,
    DEFAULT_ENABLE_NETZPUMPE_3,
    DEFAULT_ENABLE_PUFFER_2,
    DEFAULT_ENABLE_SOLAR,
    DEFAULT_ENABLE_WW1,
    DEFAULT_ENABLE_WW2,
    DEFAULT_PUFFER_MITTE_OBEN_NODE_ID,
    DEFAULT_PUFFER_MITTE_UNTEN_NODE_ID,
    DEFAULT_ERROR_THRESHOLD,
    DEFAULT_FALLBACK_PING_INTERVAL,
    DEFAULT_LOG_LEVEL,
    DEFAULT_LOG_VERSION_PREFIX,
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
    MAX_FALLBACK_PING_INTERVAL,
    MAX_LOG_LEVEL_THRESHOLD_FOR_CONNECTION_ERRORS,
    MAX_LOG_LEVEL_THRESHOLD_FOR_PREEMPTION_ERRORS,
    MAX_POLLING_PREEMPTION_TIMEOUT,
    MAX_RECENTLY_SET_POLL_IGNORE_WINDOW_S,
    MAX_SCAN_INTERVAL,
    MIN_API_TIMEOUT,
    MIN_CONNECT_TIMEOUT,
    MIN_ERROR_THRESHOLD,
    MIN_FALLBACK_PING_INTERVAL,
    MIN_LOG_LEVEL_THRESHOLD_FOR_CONNECTION_ERRORS,
    MIN_LOG_LEVEL_THRESHOLD_FOR_PREEMPTION_ERRORS,
    MIN_POLLING_PREEMPTION_TIMEOUT,
    MIN_RECENTLY_SET_POLL_IGNORE_WINDOW_S,
    MIN_SCAN_INTERVAL,
    POLLING_GROUP_DEFINITIONS,
)
from .helpers.logging_utils import _LOGGER
from .helpers.network_utils import async_execute_icmp_ping, prepare_base_url

# ---------------------------------------------------------------------------
# Section key registry — single source of truth for flatten logic
# ---------------------------------------------------------------------------

_POLLING_KEYS = [f"{CONF_SCAN_INTERVAL}_{g['key']}" for g in POLLING_GROUP_DEFINITIONS]

_SECTION_KEYS: dict[str, list[str]] = {
    "polling": _POLLING_KEYS,
    "connection": [CONF_API_TIMEOUT, CONF_CONNECT_TIMEOUT, CONF_FALLBACK_PING_INTERVAL],
    "logging": [
        CONF_LOG_LEVEL,
        CONF_ADVANCED_LOGGING,
        CONF_LOG_VERSION_PREFIX,
        CONF_SOURCE_TIMEZONE,
    ],
    "advanced": [
        CONF_POLLING_PREEMPTION_TIMEOUT,
        CONF_RECENTLY_SET_POLL_IGNORE_WINDOW_S,
        CONF_LOG_LEVEL_THRESHOLD_FOR_CONNECTION_ERRORS,
        CONF_ERROR_THRESHOLD,
        CONF_LOG_LEVEL_THRESHOLD_FOR_PREEMPTION_ERRORS,
    ],
    "components": [
        CONF_ENABLE_WW1,
        CONF_ENABLE_WW2,
        CONF_ENABLE_HK2,
        CONF_ENABLE_HK3,
        CONF_ENABLE_HK4,
        CONF_ENABLE_HK5,
        CONF_ENABLE_HK6,
        CONF_ENABLE_SOLAR,
        CONF_ENABLE_PUFFER_2,
        CONF_ENABLE_EXT_WQ,
        CONF_ENABLE_LAGER,
        CONF_ENABLE_NETZPUMPE_1,
        CONF_ENABLE_NETZPUMPE_2,
        CONF_ENABLE_NETZPUMPE_3,
    ],
    "puffer": [
        CONF_PUFFER_MITTE_OBEN_NODE_ID,
        CONF_PUFFER_MITTE_UNTEN_NODE_ID,
    ],
}

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


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
    """Validate connectivity to the HDG boiler.

    ICMP ping is attempted first as a quick reachability hint, but a ping
    failure is not fatal — ICMP is commonly blocked on VPN links or firewall
    rules. If ping fails the API test is still attempted so that hostname-based
    setups (e.g. ``hdg.fritz.box`` via WireGuard) work without extra config.
    """
    try:
        hostname = await _get_hostname_from_host_ip(host_ip)
        if not hostname:
            return False

        if not await async_execute_icmp_ping(hostname, timeout=3):
            _LOGGER.warning(
                "ICMP ping to %s failed (ICMP may be blocked). Trying API anyway.",
                hostname,
            )

        return await _test_api_connectivity(hass, host_ip)

    except (HdgApiConnectionError, HdgApiError) as err:
        _LOGGER.warning("API error during device check for %s: %s", host_ip, err)
    except Exception:
        _LOGGER.exception("Unexpected error during device check for %s", host_ip)
    return False


# ---------------------------------------------------------------------------
# Common flow mixin — shared schema, flatten, and step logic
# ---------------------------------------------------------------------------


class HdgBoilerCommonFlow:
    """Mixin providing the shared options/component schema for config and options flows."""

    def _get_current_options(self) -> dict[str, Any]:
        """Return current option values for populating form defaults."""
        return {}

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.ConfigFlowResult:
        """Show the combined options + component-group form."""
        if user_input is not None:
            processed = self._flatten_section_data(user_input)

            if (
                not processed.get(CONF_PUFFER_MITTE_OBEN_NODE_ID)
                or not str(processed.get(CONF_PUFFER_MITTE_OBEN_NODE_ID, "")).strip()
            ):
                processed[CONF_PUFFER_MITTE_OBEN_NODE_ID] = None

            if (
                not processed.get(CONF_PUFFER_MITTE_UNTEN_NODE_ID)
                or not str(processed.get(CONF_PUFFER_MITTE_UNTEN_NODE_ID, "")).strip()
            ):
                processed[CONF_PUFFER_MITTE_UNTEN_NODE_ID] = None

            return await self._async_finish_flow(processed)

        show_form = cast(Any, self).async_show_form
        return show_form(
            step_id="init",
            data_schema=self._build_options_schema(),
            description_placeholders=self._build_description_placeholders(),
        )

    async def _async_finish_flow(
        self, options: dict[str, Any]
    ) -> config_entries.ConfigFlowResult:
        """Persist the collected options. Overridden by each subclass."""
        raise NotImplementedError

    # ------------------------------------------------------------------
    # Schema builder
    # ------------------------------------------------------------------

    def _build_options_schema(self) -> vol.Schema:
        """Build the options schema with collapsible sections."""
        opts = self._get_current_options()

        def get(key: str, default: Any) -> Any:
            return opts.get(key, default)

        def num(
            min_val: float,
            max_val: float,
            step: float = 1,
            unit: str | None = None,
        ) -> NumberSelector:
            cfg: dict[str, Any] = {
                "min": min_val,
                "max": max_val,
                "step": step,
                "mode": NumberSelectorMode.BOX,
            }
            if unit:
                cfg["unit_of_measurement"] = unit
            return NumberSelector(NumberSelectorConfig(**cfg))

        # Section: Polling intervals
        polling_fields: dict[Any, Any] = {}
        for group in POLLING_GROUP_DEFINITIONS:
            key = f"{CONF_SCAN_INTERVAL}_{group['key']}"
            polling_fields[
                vol.Optional(key, default=get(key, group["default_interval"]))
            ] = num(MIN_SCAN_INTERVAL, MAX_SCAN_INTERVAL, unit="s")

        # Section: Connection
        connection_fields: dict[Any, Any] = {
            vol.Optional(
                CONF_API_TIMEOUT, default=get(CONF_API_TIMEOUT, DEFAULT_API_TIMEOUT)
            ): num(MIN_API_TIMEOUT, MAX_API_TIMEOUT, unit="s"),
            vol.Optional(
                CONF_CONNECT_TIMEOUT,
                default=get(CONF_CONNECT_TIMEOUT, DEFAULT_CONNECT_TIMEOUT),
            ): num(MIN_CONNECT_TIMEOUT, MAX_CONNECT_TIMEOUT, step=0.1, unit="s"),
            vol.Optional(
                CONF_FALLBACK_PING_INTERVAL,
                default=get(
                    CONF_FALLBACK_PING_INTERVAL, DEFAULT_FALLBACK_PING_INTERVAL
                ),
            ): num(MIN_FALLBACK_PING_INTERVAL, MAX_FALLBACK_PING_INTERVAL, unit="s"),
        }

        # Section: Logging
        logging_fields: dict[Any, Any] = {
            vol.Required(
                CONF_LOG_LEVEL, default=get(CONF_LOG_LEVEL, DEFAULT_LOG_LEVEL)
            ): SelectSelector(
                SelectSelectorConfig(
                    options=LOG_LEVELS, mode=SelectSelectorMode.DROPDOWN
                )
            ),
            vol.Optional(
                CONF_ADVANCED_LOGGING,
                default=get(CONF_ADVANCED_LOGGING, DEFAULT_ADVANCED_LOGGING),
            ): BooleanSelector(),
            vol.Optional(
                CONF_LOG_VERSION_PREFIX,
                default=get(CONF_LOG_VERSION_PREFIX, DEFAULT_LOG_VERSION_PREFIX),
            ): BooleanSelector(),
            vol.Optional(
                CONF_SOURCE_TIMEZONE,
                default=get(CONF_SOURCE_TIMEZONE, DEFAULT_SOURCE_TIMEZONE),
            ): TextSelector(),
        }

        # Section: Advanced
        advanced_fields: dict[Any, Any] = {
            vol.Optional(
                CONF_POLLING_PREEMPTION_TIMEOUT,
                default=get(
                    CONF_POLLING_PREEMPTION_TIMEOUT, DEFAULT_POLLING_PREEMPTION_TIMEOUT
                ),
            ): num(
                MIN_POLLING_PREEMPTION_TIMEOUT, MAX_POLLING_PREEMPTION_TIMEOUT, unit="s"
            ),
            vol.Optional(
                CONF_RECENTLY_SET_POLL_IGNORE_WINDOW_S,
                default=get(
                    CONF_RECENTLY_SET_POLL_IGNORE_WINDOW_S,
                    DEFAULT_RECENTLY_SET_POLL_IGNORE_WINDOW_S,
                ),
            ): num(
                MIN_RECENTLY_SET_POLL_IGNORE_WINDOW_S,
                MAX_RECENTLY_SET_POLL_IGNORE_WINDOW_S,
                unit="s",
            ),
            vol.Optional(
                CONF_LOG_LEVEL_THRESHOLD_FOR_CONNECTION_ERRORS,
                default=get(
                    CONF_LOG_LEVEL_THRESHOLD_FOR_CONNECTION_ERRORS,
                    DEFAULT_LOG_LEVEL_THRESHOLD_FOR_CONNECTION_ERRORS,
                ),
            ): num(
                MIN_LOG_LEVEL_THRESHOLD_FOR_CONNECTION_ERRORS,
                MAX_LOG_LEVEL_THRESHOLD_FOR_CONNECTION_ERRORS,
            ),
            vol.Optional(
                CONF_ERROR_THRESHOLD,
                default=get(CONF_ERROR_THRESHOLD, DEFAULT_ERROR_THRESHOLD),
            ): num(MIN_ERROR_THRESHOLD, MAX_ERROR_THRESHOLD),
            vol.Optional(
                CONF_LOG_LEVEL_THRESHOLD_FOR_PREEMPTION_ERRORS,
                default=get(
                    CONF_LOG_LEVEL_THRESHOLD_FOR_PREEMPTION_ERRORS,
                    DEFAULT_LOG_LEVEL_THRESHOLD_FOR_PREEMPTION_ERRORS,
                ),
            ): num(
                MIN_LOG_LEVEL_THRESHOLD_FOR_PREEMPTION_ERRORS,
                MAX_LOG_LEVEL_THRESHOLD_FOR_PREEMPTION_ERRORS,
            ),
        }

        # Section: Component groups (optional hardware / boiler packages).
        # One toggle per installable package — never combine independent options.
        components_fields: dict[Any, Any] = {
            vol.Optional(
                CONF_ENABLE_WW1, default=get(CONF_ENABLE_WW1, DEFAULT_ENABLE_WW1)
            ): BooleanSelector(),
            vol.Optional(
                CONF_ENABLE_WW2, default=get(CONF_ENABLE_WW2, DEFAULT_ENABLE_WW2)
            ): BooleanSelector(),
            vol.Optional(
                CONF_ENABLE_HK2, default=get(CONF_ENABLE_HK2, DEFAULT_ENABLE_HK2)
            ): BooleanSelector(),
            vol.Optional(
                CONF_ENABLE_HK3, default=get(CONF_ENABLE_HK3, DEFAULT_ENABLE_HK3)
            ): BooleanSelector(),
            vol.Optional(
                CONF_ENABLE_HK4, default=get(CONF_ENABLE_HK4, DEFAULT_ENABLE_HK4)
            ): BooleanSelector(),
            vol.Optional(
                CONF_ENABLE_HK5, default=get(CONF_ENABLE_HK5, DEFAULT_ENABLE_HK5)
            ): BooleanSelector(),
            vol.Optional(
                CONF_ENABLE_HK6, default=get(CONF_ENABLE_HK6, DEFAULT_ENABLE_HK6)
            ): BooleanSelector(),
            vol.Optional(
                CONF_ENABLE_SOLAR, default=get(CONF_ENABLE_SOLAR, DEFAULT_ENABLE_SOLAR)
            ): BooleanSelector(),
            vol.Optional(
                CONF_ENABLE_PUFFER_2,
                default=get(CONF_ENABLE_PUFFER_2, DEFAULT_ENABLE_PUFFER_2),
            ): BooleanSelector(),
            vol.Optional(
                CONF_ENABLE_EXT_WQ,
                default=get(CONF_ENABLE_EXT_WQ, DEFAULT_ENABLE_EXT_WQ),
            ): BooleanSelector(),
            vol.Optional(
                CONF_ENABLE_LAGER, default=get(CONF_ENABLE_LAGER, DEFAULT_ENABLE_LAGER)
            ): BooleanSelector(),
            vol.Optional(
                CONF_ENABLE_NETZPUMPE_1,
                default=get(CONF_ENABLE_NETZPUMPE_1, DEFAULT_ENABLE_NETZPUMPE_1),
            ): BooleanSelector(),
            vol.Optional(
                CONF_ENABLE_NETZPUMPE_2,
                default=get(CONF_ENABLE_NETZPUMPE_2, DEFAULT_ENABLE_NETZPUMPE_2),
            ): BooleanSelector(),
            vol.Optional(
                CONF_ENABLE_NETZPUMPE_3,
                default=get(CONF_ENABLE_NETZPUMPE_3, DEFAULT_ENABLE_NETZPUMPE_3),
            ): BooleanSelector(),
        }

        puffer_fields: dict[Any, Any] = {
            vol.Optional(
                CONF_PUFFER_MITTE_OBEN_NODE_ID,
                description={
                    "suggested_value": get(
                        CONF_PUFFER_MITTE_OBEN_NODE_ID,
                        DEFAULT_PUFFER_MITTE_OBEN_NODE_ID,
                    )
                    or "",
                },
            ): TextSelector(),
            vol.Optional(
                CONF_PUFFER_MITTE_UNTEN_NODE_ID,
                description={
                    "suggested_value": get(
                        CONF_PUFFER_MITTE_UNTEN_NODE_ID,
                        DEFAULT_PUFFER_MITTE_UNTEN_NODE_ID,
                    )
                    or "",
                },
            ): TextSelector(),
        }

        return vol.Schema(
            {
                vol.Required("components"): data_entry_flow.section(
                    vol.Schema(components_fields),
                    {"collapsed": False},
                ),
                vol.Required("puffer"): data_entry_flow.section(
                    vol.Schema(puffer_fields),
                    {"collapsed": True},
                ),
                vol.Required("polling"): data_entry_flow.section(
                    vol.Schema(polling_fields),
                    {"collapsed": True},
                ),
                vol.Required("connection"): data_entry_flow.section(
                    vol.Schema(connection_fields),
                    {"collapsed": True},
                ),
                vol.Required("logging"): data_entry_flow.section(
                    vol.Schema(logging_fields),
                    {"collapsed": True},
                ),
                vol.Required("advanced"): data_entry_flow.section(
                    vol.Schema(advanced_fields),
                    {"collapsed": True},
                ),
            }
        )

    # ------------------------------------------------------------------
    # Flatten nested section data → flat options dict
    # ------------------------------------------------------------------

    @staticmethod
    def _flatten_section_data(user_input: dict[str, Any]) -> dict[str, Any]:
        """Flatten collapsible section data into a flat options dict."""
        result: dict[str, Any] = {}
        for section_name, keys in _SECTION_KEYS.items():
            if section_name in user_input:
                section_data = user_input[section_name]
                for key in keys:
                    if key in section_data:
                        result[key] = section_data[key]
                    elif section_name == "puffer":
                        result[key] = None
        return result

    # ------------------------------------------------------------------
    # Description placeholders (used in data_description translations)
    # ------------------------------------------------------------------

    @staticmethod
    def _build_description_placeholders() -> dict[str, str]:
        """Build placeholders referenced in translation data_description fields."""
        placeholders: dict[str, Any] = {
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
            "min_fallback_ping_interval": MIN_FALLBACK_PING_INTERVAL,
            "max_fallback_ping_interval": MAX_FALLBACK_PING_INTERVAL,
            "default_fallback_ping_interval": DEFAULT_FALLBACK_PING_INTERVAL,
        }
        result = {k: str(v) for k, v in placeholders.items()}
        for group in POLLING_GROUP_DEFINITIONS:
            result[f"default_scan_interval_{group['key']}"] = str(
                group["default_interval"]
            )
        return result


# ---------------------------------------------------------------------------
# Config flow
# ---------------------------------------------------------------------------


@config_entries.HANDLERS.register(DOMAIN)
class HdgBoilerConfigFlow(HdgBoilerCommonFlow, config_entries.ConfigFlow):
    """Handle a config flow for HDG Bavaria Boiler."""

    VERSION = 1

    def __init__(self) -> None:
        """Initialize the config flow."""
        self._host_data: dict[str, Any] = {}

    @staticmethod
    @callback
    def async_get_options_flow(
        config_entry: config_entries.ConfigEntry,
    ) -> HdgBoilerOptionsFlowHandler:
        """Get the options flow for this handler."""
        return HdgBoilerOptionsFlowHandler()

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.ConfigFlowResult:
        """Handle the initial user step (host + alias)."""
        errors: dict[str, str] = {}
        if user_input is not None:
            host_ip = user_input[CONF_HOST_IP]
            if await _validate_host_connectivity(self.hass, host_ip):
                await self.async_set_unique_id(host_ip.lower())
                self._abort_if_unique_id_configured()
                self._host_data = user_input
                return await self.async_step_init()
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

    async def _async_finish_flow(
        self, options: dict[str, Any]
    ) -> config_entries.ConfigFlowResult:
        """Create the config entry with host data + flattened options."""
        host_ip = self._host_data[CONF_HOST_IP]
        title = self._host_data.get(CONF_DEVICE_ALIAS) or f"HDG Boiler ({host_ip})"
        return self.async_create_entry(
            title=title, data=self._host_data, options=options
        )


# ---------------------------------------------------------------------------
# Options flow
# ---------------------------------------------------------------------------


class HdgBoilerOptionsFlowHandler(HdgBoilerCommonFlow, config_entries.OptionsFlow):
    """Handle an options flow for HDG Bavaria Boiler."""

    def __init__(self) -> None:
        """Initialize options flow."""
        self._data: dict[str, Any] = {}

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.ConfigFlowResult:
        """Start the options flow."""
        return await super().async_step_init(user_input)

    def _get_current_options(self) -> dict[str, Any]:
        """Return current options for form."""
        opts = dict(self.config_entry.options)
        for conf in (
            CONF_PUFFER_MITTE_OBEN_NODE_ID,
            CONF_PUFFER_MITTE_UNTEN_NODE_ID,
        ):
            val = opts.get(conf)
            if val is None or not str(val).strip():
                opts[conf] = ""
        return opts

    async def _async_finish_flow(
        self, options: dict[str, Any]
    ) -> config_entries.ConfigFlowResult:
        """Update the config entry."""
        self._data |= options

        new_options = dict(self.config_entry.options) | self._data
        if (
            not new_options.get(CONF_PUFFER_MITTE_OBEN_NODE_ID)
            or not str(new_options.get(CONF_PUFFER_MITTE_OBEN_NODE_ID, "")).strip()
        ):
            new_options[CONF_PUFFER_MITTE_OBEN_NODE_ID] = None

        if (
            not new_options.get(CONF_PUFFER_MITTE_UNTEN_NODE_ID)
            or not str(new_options.get(CONF_PUFFER_MITTE_UNTEN_NODE_ID, "")).strip()
        ):
            new_options[CONF_PUFFER_MITTE_UNTEN_NODE_ID] = None

        self.hass.config_entries.async_update_entry(
            self.config_entry, options=new_options
        )
        return self.async_create_entry(title="", data=new_options)
