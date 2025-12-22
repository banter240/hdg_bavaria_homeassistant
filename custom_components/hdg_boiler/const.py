# ruff: noqa: F401
"""Constants for the HDG Bavaria Boiler integration."""

from __future__ import annotations

from typing import Final

from homeassistant.const import UnitOfMass

from .models import PollingGroupStaticDefinition

__all__: Final[list[str]] = [
    "DOMAIN",
    "DEFAULT_NAME",
    "MANUFACTURER",
    "MODEL_PREFIX",
    "UNIT_MASS_TONNES",
    "CONF_DEVICE_ALIAS",
    "CONF_HOST_IP",
    "CONF_SOURCE_TIMEZONE",
    "CONF_API_TIMEOUT",
    "CONF_CONNECT_TIMEOUT",
    "CONF_POLLING_PREEMPTION_TIMEOUT",
    "CONF_RECENTLY_SET_POLL_IGNORE_WINDOW_S",
    "CONF_LOG_LEVEL",
    "CONF_ADVANCED_LOGGING",
    "CONF_LOG_LEVEL_THRESHOLD_FOR_CONNECTION_ERRORS",
    "CONF_ERROR_THRESHOLD",
    "CONF_LOG_LEVEL_THRESHOLD_FOR_PREEMPTION_ERRORS",
    "CONF_FALLBACK_PING_INTERVAL",
    "CONFIG_FLOW_API_TIMEOUT",
    "DEFAULT_API_TIMEOUT",
    "MIN_API_TIMEOUT",
    "MAX_API_TIMEOUT",
    "DEFAULT_CONNECT_TIMEOUT",
    "MIN_CONNECT_TIMEOUT",
    "MAX_CONNECT_TIMEOUT",
    "DEFAULT_POLLING_PREEMPTION_TIMEOUT",
    "MIN_POLLING_PREEMPTION_TIMEOUT",
    "MAX_POLLING_PREEMPTION_TIMEOUT",
    "DEFAULT_FALLBACK_PING_INTERVAL",
    "MIN_FALLBACK_PING_INTERVAL",
    "MAX_FALLBACK_PING_INTERVAL",
    "DEFAULT_RECENTLY_SET_POLL_IGNORE_WINDOW_S",
    "MIN_RECENTLY_SET_POLL_IGNORE_WINDOW_S",
    "MAX_RECENTLY_SET_POLL_IGNORE_WINDOW_S",
    "DEFAULT_LOG_LEVEL",
    "DEFAULT_ADVANCED_LOGGING",
    "DEFAULT_LOG_LEVEL_THRESHOLD_FOR_CONNECTION_ERRORS",
    "MIN_LOG_LEVEL_THRESHOLD_FOR_CONNECTION_ERRORS",
    "MAX_LOG_LEVEL_THRESHOLD_FOR_CONNECTION_ERRORS",
    "DEFAULT_ERROR_THRESHOLD",
    "MIN_ERROR_THRESHOLD",
    "MAX_ERROR_THRESHOLD",
    "DEFAULT_LOG_LEVEL_THRESHOLD_FOR_PREEMPTION_ERRORS",
    "MIN_LOG_LEVEL_THRESHOLD_FOR_PREEMPTION_ERRORS",
    "MAX_LOG_LEVEL_THRESHOLD_FOR_PREEMPTION_ERRORS",
    "DEFAULT_SOURCE_TIMEZONE",
    "API_ENDPOINT_DATA_REFRESH",
    "API_ENDPOINT_SET_VALUE",
    "CONFIG_FLOW_TEST_PAYLOAD",
    "API_REQUEST_TYPE_SET_NODE_VALUE",
    "API_REQUEST_TYPE_GET_NODES_DATA",
    "ACCEPTED_CONTENT_TYPES",
    "HDG_UNAVAILABLE_STRINGS",
    "HDG_DATETIME_SPECIAL_TEXT",
    "KNOWN_HDG_API_SETTER_SUFFIXES",
    "INITIAL_REFRESH_API_TIMEOUT_OVERRIDE",
    "POST_INITIAL_REFRESH_COOLDOWN_S",
    "INITIAL_SEQUENTIAL_INTER_GROUP_DELAY_S",
    "SET_NODE_COOLDOWN_S",
    "DEFAULT_SET_VALUE_DEBOUNCE_DELAY_S",
    "MIN_SCAN_INTERVAL",
    "MAX_SCAN_INTERVAL",
    "COORDINATOR_FALLBACK_UPDATE_INTERVAL_MINUTES",
    "COORDINATOR_MAX_CONSECUTIVE_FAILURES_BEFORE_FALLBACK",
    "FALLBACK_PING_INTERVAL_S",
    "POLLING_RETRY_INITIAL_DELAY_S",
    "POLLING_RETRY_MAX_DELAY_S",
    "POLLING_RETRY_BACKOFF_FACTOR",
    "POLLING_RETRY_MAX_ATTEMPTS",
    "SET_VALUE_RETRY_ATTEMPTS",
    "SET_VALUE_RETRY_DELAY_S",
    "SERVICE_GET_NODE_VALUE",
    "SERVICE_SET_NODE_VALUE",
    "ATTR_NODE_ID",
    "ATTR_VALUE",
    "LOG_LEVELS",
    "LIFECYCLE_LOGGER_NAME",
    "ENTITY_DETAIL_LOGGER_NAME",
    "API_LOGGER_NAME",
    "HEURISTICS_LOGGER_NAME",
    "PROCESSOR_LOGGER_NAME",
    "USER_ACTION_LOGGER_NAME",
    "DIAGNOSTICS_TO_REDACT_CONFIG_KEYS",
    "DIAGNOSTICS_SENSITIVE_COORDINATOR_DATA_NODE_IDS",
    "DIAGNOSTICS_REDACTED_PLACEHOLDER",
    "POLLING_GROUP_DEFINITIONS",
]

__version__: Final[str] = "0.13.0"

# --------------------------------------------------------------------------------
# Compatibility Shims
# --------------------------------------------------------------------------------
# Home Assistant versions before 2025.x might not have TONNES in UnitOfMass
UNIT_MASS_TONNES: Final[str] = getattr(UnitOfMass, "TONNES", "t")

# --------------------------------------------------------------------------------
# Core Integration Constants
# --------------------------------------------------------------------------------
DOMAIN: Final[str] = "hdg_boiler"
DEFAULT_NAME: Final[str] = "HDG Boiler"
MANUFACTURER: Final[str] = "HDG Bavaria GmbH"
MODEL_PREFIX: Final[str] = "HDG"


# --------------------------------------------------------------------------------
# Configuration Keys (used in config flows and options)
# --------------------------------------------------------------------------------
CONF_DEVICE_ALIAS: Final[str] = "device_alias"
CONF_HOST_IP: Final[str] = "host_ip"
CONF_SOURCE_TIMEZONE: Final[str] = "source_timezone"
CONF_API_TIMEOUT: Final[str] = "api_timeout"
CONF_CONNECT_TIMEOUT: Final[str] = "connect_timeout"
CONF_POLLING_PREEMPTION_TIMEOUT: Final[str] = "polling_preemption_timeout"
CONF_RECENTLY_SET_POLL_IGNORE_WINDOW_S: Final[str] = "recently_set_poll_ignore_window_s"
CONF_LOG_LEVEL: Final[str] = "log_level"
CONF_ADVANCED_LOGGING: Final[str] = "advanced_logging"
CONF_LOG_LEVEL_THRESHOLD_FOR_CONNECTION_ERRORS: Final[str] = (
    "log_level_threshold_for_connection_errors"
)
CONF_ERROR_THRESHOLD: Final[str] = "error_threshold"
CONF_LOG_LEVEL_THRESHOLD_FOR_PREEMPTION_ERRORS: Final[str] = (
    "log_level_threshold_for_preemption_errors"
)
CONF_FALLBACK_PING_INTERVAL: Final[str] = "fallback_ping_interval"

# --------------------------------------------------------------------------------
# Default Values & Limits for Configuration
# --------------------------------------------------------------------------------
# Timeouts
CONFIG_FLOW_API_TIMEOUT: Final[int] = 15
DEFAULT_API_TIMEOUT: Final[int] = 15
MIN_API_TIMEOUT: Final[int] = 5
MAX_API_TIMEOUT: Final[int] = 120

DEFAULT_CONNECT_TIMEOUT: Final[float] = 5.0
MIN_CONNECT_TIMEOUT: Final[float] = 3.0
MAX_CONNECT_TIMEOUT: Final[float] = 20.0

DEFAULT_POLLING_PREEMPTION_TIMEOUT: Final[int] = 5
MIN_POLLING_PREEMPTION_TIMEOUT: Final[int] = 1
MAX_POLLING_PREEMPTION_TIMEOUT: Final[int] = 20

# Polling & Fallback

DEFAULT_FALLBACK_PING_INTERVAL: Final[int] = 30
MIN_FALLBACK_PING_INTERVAL: Final[int] = 5
MAX_FALLBACK_PING_INTERVAL: Final[int] = 300

DEFAULT_RECENTLY_SET_POLL_IGNORE_WINDOW_S: Final[int] = 10
MIN_RECENTLY_SET_POLL_IGNORE_WINDOW_S: Final[int] = 5
MAX_RECENTLY_SET_POLL_IGNORE_WINDOW_S: Final[int] = 30

# Logging & Error Thresholds
DEFAULT_LOG_LEVEL: Final[str] = "INFO"
DEFAULT_ADVANCED_LOGGING: Final[bool] = False

DEFAULT_LOG_LEVEL_THRESHOLD_FOR_CONNECTION_ERRORS: Final[int] = 5
MIN_LOG_LEVEL_THRESHOLD_FOR_CONNECTION_ERRORS: Final[int] = 1
MAX_LOG_LEVEL_THRESHOLD_FOR_CONNECTION_ERRORS: Final[int] = 60

DEFAULT_ERROR_THRESHOLD: Final[int] = 3
MIN_ERROR_THRESHOLD: Final[int] = 1
MAX_ERROR_THRESHOLD: Final[int] = 20

DEFAULT_LOG_LEVEL_THRESHOLD_FOR_PREEMPTION_ERRORS: Final[int] = 3
MIN_LOG_LEVEL_THRESHOLD_FOR_PREEMPTION_ERRORS: Final[int] = 1
MAX_LOG_LEVEL_THRESHOLD_FOR_PREEMPTION_ERRORS: Final[int] = 10

# Other
DEFAULT_SOURCE_TIMEZONE: Final[str] = "Europe/Berlin"


# --------------------------------------------------------------------------------
# API Communication
# --------------------------------------------------------------------------------
# API Endpoints
API_ENDPOINT_DATA_REFRESH: Final[str] = "/ApiManager.php?action=dataRefresh"
API_ENDPOINT_SET_VALUE: Final[str] = "/ActionManager.php?action=set_value_changed"

# API Payloads & Request Types
CONFIG_FLOW_TEST_PAYLOAD: Final[str] = "nodes=1T-2T-3T-4T"
API_REQUEST_TYPE_SET_NODE_VALUE: Final[str] = "set_node_value"
API_REQUEST_TYPE_GET_NODES_DATA: Final[str] = "get_nodes_data"

# API Data Interpretation
ACCEPTED_CONTENT_TYPES: Final[set[str]] = {"application/json", "text/plain"}
HDG_UNAVAILABLE_STRINGS: Final[set[str]] = {"---", "unavailable", "none", "n/a"}
HDG_DATETIME_SPECIAL_TEXT: Final[str] = "größer 7 tage"
KNOWN_HDG_API_SETTER_SUFFIXES: Final[set[str]] = {"T", "U", "V", "W", "X", "Y"}


# --------------------------------------------------------------------------------
# Polling & Update Behavior
# --------------------------------------------------------------------------------
# Timing & Delays
INITIAL_REFRESH_API_TIMEOUT_OVERRIDE: Final[float] = 30.0
POST_INITIAL_REFRESH_COOLDOWN_S: Final[float] = 5.0
INITIAL_SEQUENTIAL_INTER_GROUP_DELAY_S: Final[float] = 0.5
SET_NODE_COOLDOWN_S: Final[float] = 2.0
DEFAULT_SET_VALUE_DEBOUNCE_DELAY_S: Final[float] = 2.0

# Scan Intervals
MIN_SCAN_INTERVAL: Final[int] = 15
MAX_SCAN_INTERVAL: Final[int] = 86430

# Fallback & Retry Mechanisms
COORDINATOR_FALLBACK_UPDATE_INTERVAL_MINUTES: Final[int] = 5
COORDINATOR_MAX_CONSECUTIVE_FAILURES_BEFORE_FALLBACK: Final[int] = 3
FALLBACK_PING_INTERVAL_S: Final[int] = 30
POLLING_RETRY_INITIAL_DELAY_S: Final[float] = 60.0
POLLING_RETRY_MAX_DELAY_S: Final[float] = 300.0
POLLING_RETRY_BACKOFF_FACTOR: Final[float] = 2.0
POLLING_RETRY_MAX_ATTEMPTS: Final[int] = 5
SET_VALUE_RETRY_ATTEMPTS: Final[int] = 3
SET_VALUE_RETRY_DELAY_S: Final[float] = 2.0


# --------------------------------------------------------------------------------
# Service Definitions
# --------------------------------------------------------------------------------
SERVICE_GET_NODE_VALUE: Final[str] = "get_node_value"
SERVICE_SET_NODE_VALUE: Final[str] = "set_node_value"
ATTR_NODE_ID: Final[str] = "node_id"
ATTR_VALUE: Final[str] = "value"


# --------------------------------------------------------------------------------
# Logging
# --------------------------------------------------------------------------------
LOG_LEVELS: Final[list[str]] = ["DEBUG", "INFO", "WARNING", "ERROR"]
LIFECYCLE_LOGGER_NAME: Final[str] = f"{DOMAIN}.lifecycle"
ENTITY_DETAIL_LOGGER_NAME: Final[str] = f"{DOMAIN}.entity_detail"
API_LOGGER_NAME: Final[str] = f"{DOMAIN}.api"
HEURISTICS_LOGGER_NAME: Final[str] = f"{DOMAIN}.heuristics"
PROCESSOR_LOGGER_NAME: Final[str] = f"{DOMAIN}.processor"
USER_ACTION_LOGGER_NAME: Final[str] = f"{DOMAIN}.user_action"


# --------------------------------------------------------------------------------
# Diagnostics
# --------------------------------------------------------------------------------
DIAGNOSTICS_TO_REDACT_CONFIG_KEYS: Final[set[str]] = {CONF_HOST_IP}
DIAGNOSTICS_SENSITIVE_COORDINATOR_DATA_NODE_IDS: Final[set[str]] = {
    "20026",
    "20031",
    "20039",
}
DIAGNOSTICS_REDACTED_PLACEHOLDER: Final[str] = "REDACTED"


# --------------------------------------------------------------------------------
# Static Definitions
# --------------------------------------------------------------------------------
POLLING_GROUP_DEFINITIONS: Final[list[PollingGroupStaticDefinition]] = [
    {"key": "group_1", "default_interval": 15},
    {"key": "group_2", "default_interval": 304},
    {"key": "group_3", "default_interval": 86410},
    {"key": "group_4", "default_interval": 86420},
    {"key": "group_5", "default_interval": 86430},
]
