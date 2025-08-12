# ruff: noqa: F401
"""Constants for the HDG Bavaria Boiler integration."""

from __future__ import annotations

from typing import Final

from .models import PollingGroupStaticDefinition

__all__: Final[list[str]] = [
    "DOMAIN",
    "DEFAULT_NAME",
    "MANUFACTURER",
    "MODEL_PREFIX",
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
    "DEFAULT_RECENTLY_SET_POLL_IGNORE_WINDOW_S",
    "MIN_RECENTLY_SET_POLL_IGNORE_WINDOW_S",
    "MAX_RECENTLY_SET_POLL_IGNORE_WINDOW_S",
    "DEFAULT_LOG_LEVEL",
    "DEFAULT_ADVANCED_LOGGING",
    "DEFAULT_LOG_LEVEL_THRESHOLD_FOR_CONNECTION_ERRORS",
    "MIN_LOG_LEVEL_THRESHOLD_FOR_CONNECTION_ERRORS",
    "MAX_LOG_LEVEL_THRESHOLD_FOR_CONNECTION_ERRORS",
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

__version__: Final[str] = "1.2.3"

# --------------------------------------------------------------------------------
# Core Integration Constants
# --------------------------------------------------------------------------------
DOMAIN: Final[str] = "hdg_boiler"  # The domain of the integration.
DEFAULT_NAME: Final[str] = "HDG Boiler"  # Default name for the integration.
MANUFACTURER: Final[str] = "HDG Bavaria GmbH"  # Manufacturer of the boiler.
MODEL_PREFIX: Final[str] = "HDG"  # Prefix for device models.


# --------------------------------------------------------------------------------
# Configuration Keys (used in config flows and options)
# --------------------------------------------------------------------------------
CONF_DEVICE_ALIAS: Final[str] = "device_alias"  # User-defined alias for the device.
CONF_HOST_IP: Final[str] = "host_ip"  # IP address of the HDG boiler.
CONF_SOURCE_TIMEZONE: Final[str] = "source_timezone"  # Timezone for parsing datetimes.
CONF_API_TIMEOUT: Final[str] = "api_timeout"  # General API timeout.
CONF_CONNECT_TIMEOUT: Final[str] = "connect_timeout"  # Connection-specific timeout.
CONF_POLLING_PREEMPTION_TIMEOUT: Final[str] = (
    "polling_preemption_timeout"  # Timeout for low-priority polls when a high-priority one is pending.
)
CONF_RECENTLY_SET_POLL_IGNORE_WINDOW_S: Final[str] = (
    "recently_set_poll_ignore_window_s"  # Time window to ignore updates for recently set values.
)
CONF_LOG_LEVEL: Final[str] = "log_level"  # Basic logging level.
CONF_ADVANCED_LOGGING: Final[str] = "advanced_logging"  # Toggle for detailed loggers.
CONF_LOG_LEVEL_THRESHOLD_FOR_CONNECTION_ERRORS: Final[str] = (
    "log_level_threshold_for_connection_errors"  # Number of failures before logging connection errors as ERROR.
)
CONF_ERROR_THRESHOLD: Final[str] = (
    "error_threshold"  # Number of consecutive errors before logging.
)


# --------------------------------------------------------------------------------
# Default Values & Limits for Configuration
# --------------------------------------------------------------------------------
# Timeouts
CONFIG_FLOW_API_TIMEOUT: Final[int] = (
    15  # Shorter timeout for config flow connectivity check to fail fast.
)
DEFAULT_API_TIMEOUT: Final[int] = 15  # Default seconds for general API timeout.
MIN_API_TIMEOUT: Final[int] = 5
MAX_API_TIMEOUT: Final[int] = 120

DEFAULT_CONNECT_TIMEOUT: Final[float] = 5.0  # Default seconds for connection timeout.
MIN_CONNECT_TIMEOUT: Final[float] = 3.0
MAX_CONNECT_TIMEOUT: Final[float] = 20.0

DEFAULT_POLLING_PREEMPTION_TIMEOUT: Final[int] = (
    5  # Default for how long a LOW priority request runs if a higher priority request is pending.
)
MIN_POLLING_PREEMPTION_TIMEOUT: Final[int] = 1
MAX_POLLING_PREEMPTION_TIMEOUT: Final[int] = 20

# Polling
DEFAULT_RECENTLY_SET_POLL_IGNORE_WINDOW_S: Final[int] = (
    10  # Default time window to ignore updates for recently set values.
)
MIN_RECENTLY_SET_POLL_IGNORE_WINDOW_S: Final[int] = 5
MAX_RECENTLY_SET_POLL_IGNORE_WINDOW_S: Final[int] = 30

# Logging
DEFAULT_LOG_LEVEL: Final[str] = "INFO"  # Default logging level.
DEFAULT_ADVANCED_LOGGING: Final[bool] = False  # Default for advanced logging.
DEFAULT_LOG_LEVEL_THRESHOLD_FOR_CONNECTION_ERRORS: Final[int] = (
    5  # Default to 5 consecutive failures before logging as ERROR.
)
MIN_LOG_LEVEL_THRESHOLD_FOR_CONNECTION_ERRORS: Final[int] = (
    1  # Minimum 1 (always log as ERROR).
)
MAX_LOG_LEVEL_THRESHOLD_FOR_CONNECTION_ERRORS: Final[int] = (
    60  # Maximum 60 (log as WARNING for a long time).
)
DEFAULT_ERROR_THRESHOLD: Final[int] = (
    3  # Default number of consecutive errors before logging.
)
MIN_ERROR_THRESHOLD: Final[int] = 1
MAX_ERROR_THRESHOLD: Final[int] = 20

# Other
DEFAULT_SOURCE_TIMEZONE: Final[str] = (
    "Europe/Berlin"  # For parsing datetimes from the boiler.
)


# --------------------------------------------------------------------------------
# API Communication
# --------------------------------------------------------------------------------
# API Endpoints
API_ENDPOINT_DATA_REFRESH: Final[str] = "/ApiManager.php?action=dataRefresh"
API_ENDPOINT_SET_VALUE: Final[str] = "/ActionManager.php?action=set_value_changed"

# API Payloads & Request Types
CONFIG_FLOW_TEST_PAYLOAD: Final[str] = (
    "nodes=1T-2T-3T-4T"  # Payload for initial connectivity test in config flow.
)
API_REQUEST_TYPE_SET_NODE_VALUE: Final[str] = "set_node_value"
API_REQUEST_TYPE_GET_NODES_DATA: Final[str] = "get_nodes_data"

# API Data Interpretation
ACCEPTED_CONTENT_TYPES: Final[set[str]] = {
    "application/json",
    "text/plain",
}  # Content types the API client accepts.
HDG_UNAVAILABLE_STRINGS: Final[set[str]] = {
    "---",
    "unavailable",
    "none",
    "n/a",
}  # Strings indicating an unavailable state.
HDG_DATETIME_SPECIAL_TEXT: Final[str] = (
    "größer 7 tage"  # Special text for datetimes older than 7 days.
)
KNOWN_HDG_API_SETTER_SUFFIXES: Final[set[str]] = {
    "T",
    "U",
    "V",
    "W",
    "X",
    "Y",
}  # Suffixes for nodes that can be set.


# --------------------------------------------------------------------------------
# Polling & Update Behavior
# --------------------------------------------------------------------------------
# Timing & Delays
INITIAL_REFRESH_API_TIMEOUT_OVERRIDE: Final[float] = (
    30.0  # A more generous timeout for the very first data refresh.
)
POST_INITIAL_REFRESH_COOLDOWN_S: Final[float] = (
    5.0  # Cooldown period after the initial full data refresh.
)
INITIAL_SEQUENTIAL_INTER_GROUP_DELAY_S: Final[float] = (
    0.5  # Short delay between fetching polling groups during initial refresh.
)
SET_NODE_COOLDOWN_S: Final[float] = (
    2.0  # Cooldown period after setting a value before next poll.
)
DEFAULT_SET_VALUE_DEBOUNCE_DELAY_S: Final[float] = (
    2.0  # Default debounce delay for setting values to bundle rapid changes.
)

# Scan Intervals
MIN_SCAN_INTERVAL: Final[int] = 15  # Minimum allowable scan interval in seconds.
MAX_SCAN_INTERVAL: Final[int] = 86430  # Maximum allowable scan interval.

# Fallback & Retry Mechanisms
COORDINATOR_FALLBACK_UPDATE_INTERVAL_MINUTES: Final[int] = (
    5  # Fallback update interval if the coordinator experiences repeated failures.
)
COORDINATOR_MAX_CONSECUTIVE_FAILURES_BEFORE_FALLBACK: Final[int] = (
    3  # Number of failures before switching to the fallback interval.
)
POLLING_RETRY_INITIAL_DELAY_S: Final[float] = (
    60.0  # Initial delay for retrying a failed poll.
)
POLLING_RETRY_MAX_DELAY_S: Final[float] = (
    300.0  # Maximum delay for retrying a failed poll.
)
POLLING_RETRY_BACKOFF_FACTOR: Final[float] = (
    2.0  # Backoff factor for exponential retry delay.
)
POLLING_RETRY_MAX_ATTEMPTS: Final[int] = (
    5  # Maximum number of retry attempts for polling.
)
SET_VALUE_RETRY_ATTEMPTS: Final[int] = (
    3  # Maximum number of retry attempts for setting a value.
)
SET_VALUE_RETRY_DELAY_S: Final[float] = (
    2.0  # Delay between retries when setting a value.
)


# --------------------------------------------------------------------------------
# Service Definitions
# --------------------------------------------------------------------------------
SERVICE_GET_NODE_VALUE: Final[str] = "get_node_value"
SERVICE_SET_NODE_VALUE: Final[str] = "set_node_value"
ATTR_NODE_ID: Final[str] = "node_id"  # Attribute for node ID in service calls.
ATTR_VALUE: Final[str] = "value"  # Attribute for value in service calls.


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
DIAGNOSTICS_TO_REDACT_CONFIG_KEYS: Final[set[str]] = {
    CONF_HOST_IP
}  # Config keys to redact in diagnostics.
DIAGNOSTICS_SENSITIVE_COORDINATOR_DATA_NODE_IDS: Final[set[str]] = {
    "20026",
    "20031",
    "20039",
}  # Node IDs containing sensitive data to be redacted.
DIAGNOSTICS_REDACTED_PLACEHOLDER: Final[str] = (
    "REDACTED"  # Placeholder for redacted data.
)


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
