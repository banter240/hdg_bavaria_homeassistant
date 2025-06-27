"""Constants for the HDG Bavaria Boiler integration.

This module centralizes all constants used across the HDG Bavaria Boiler
integration. Constants are grouped by their functional area, such as core
integration details, API communication parameters, data interpretation rules,
configuration keys and defaults, polling and update behavior controls,
service definitions, and diagnostic settings.
"""

from typing import Final

from .models import PollingGroupStaticDefinition

# Core integration constants
DOMAIN: Final = "hdg_boiler"
DEFAULT_NAME: Final = "HDG Boiler"
MANUFACTURER: Final = "HDG Bavaria GmbH"
MODEL_PREFIX: Final = "HDG"

# API communication
API_ENDPOINT_DATA_REFRESH: Final = "/ApiManager.php?action=dataRefresh"
API_ENDPOINT_SET_VALUE: Final = "/ActionManager.php?action=set_value_changed"
CONFIG_FLOW_TEST_PAYLOAD: Final = (
    "nodes=1T-2T-3T-4T"  # Payload for initial connectivity test in config flow.
)

# API timeouts (seconds)
CONFIG_FLOW_API_TIMEOUT: Final = (
    15  # Shorter timeout for config flow connectivity check to fail fast.
)

CONF_API_TIMEOUT: Final = "api_timeout"
DEFAULT_API_TIMEOUT: Final = 15
MIN_API_TIMEOUT: Final = 5
MAX_API_TIMEOUT: Final = 120

CONF_CONNECT_TIMEOUT: Final = "connect_timeout"
DEFAULT_CONNECT_TIMEOUT: Final = 5.0
MIN_CONNECT_TIMEOUT: Final = 3.0
MAX_CONNECT_TIMEOUT: Final = 20.0

CONF_POLLING_PREEMPTION_TIMEOUT: Final = "polling_preemption_timeout"
DEFAULT_POLLING_PREEMPTION_TIMEOUT: Final = 5.0  # Default for how long a LOW priority request runs if a higher priority request is pending.
MIN_POLLING_PREEMPTION_TIMEOUT: Final = 1.0
MAX_POLLING_PREEMPTION_TIMEOUT: Final = 20.0

INITIAL_REFRESH_API_TIMEOUT_OVERRIDE: Final = 30.0
POST_INITIAL_REFRESH_COOLDOWN_S: Final = 5.0

API_REQUEST_TYPE_SET_NODE_VALUE: Final = "set_node_value"
API_REQUEST_TYPE_GET_NODES_DATA: Final = "get_nodes_data"


# API data interpretation
HDG_UNAVAILABLE_STRINGS: Final[set[str]] = {"---", "unavailable", "none", "n/a"}
HDG_DATETIME_SPECIAL_TEXT: Final = "größer 7 tage"
KNOWN_HDG_API_SETTER_SUFFIXES: Final[set[str]] = {"T", "U", "V", "W", "X", "Y"}

# Configuration & Options Flow
CONF_DEVICE_ALIAS: Final = "device_alias"
CONF_HOST_IP: Final = "host_ip"
CONF_SOURCE_TIMEZONE: Final = "source_timezone"


DEFAULT_SOURCE_TIMEZONE: Final = (
    "Europe/Berlin"  # For parsing datetimes from the boiler.
)

CONF_LOG_LEVEL: Final = "log_level"
LOG_LEVELS: Final = ["DEBUG", "INFO", "WARNING", "ERROR"]
DEFAULT_LOG_LEVEL: Final = "INFO"
CONF_ADVANCED_LOGGING: Final = "advanced_logging"
DEFAULT_ADVANCED_LOGGING: Final = False

LIFECYCLE_LOGGER_NAME: Final = f"{DOMAIN}.lifecycle"
ENTITY_DETAIL_LOGGER_NAME: Final = f"{DOMAIN}.entity_detail"
API_LOGGER_NAME: Final = f"{DOMAIN}.api"
HEURISTICS_LOGGER_NAME: Final = f"{DOMAIN}.heuristics"
PROCESSOR_LOGGER_NAME: Final = f"{DOMAIN}.processor"
USER_ACTION_LOGGER_NAME: Final = f"{DOMAIN}.user_action"

CONF_LOG_LEVEL_THRESHOLD_FOR_CONNECTION_ERRORS: Final = (
    "log_level_threshold_for_connection_errors"
)
DEFAULT_LOG_LEVEL_THRESHOLD_FOR_CONNECTION_ERRORS: Final = (
    5  # Default to 5 consecutive failures before logging as ERROR
)
MIN_LOG_LEVEL_THRESHOLD_FOR_CONNECTION_ERRORS: Final = (
    1  # Minimum 1 (always log as ERROR)
)
MAX_LOG_LEVEL_THRESHOLD_FOR_CONNECTION_ERRORS: Final = (
    60  # Maximum 60 (log as WARNING for a long time)
)

POLLING_GROUP_DEFINITIONS: Final[list[PollingGroupStaticDefinition]] = [
    {"key": "group_1", "default_interval": 15},
    {"key": "group_2", "default_interval": 304},
    {"key": "group_3", "default_interval": 86410},
    {"key": "group_4", "default_interval": 86420},
    {"key": "group_5", "default_interval": 86430},
]

# Polling & Update Behavior
INITIAL_SEQUENTIAL_INTER_GROUP_DELAY_S: Final = 0.5
SET_NODE_COOLDOWN_S: Final = 2.0

CONF_RECENTLY_SET_POLL_IGNORE_WINDOW_S: Final = "recently_set_poll_ignore_window_s"
DEFAULT_RECENTLY_SET_POLL_IGNORE_WINDOW_S: Final[float] = 10.0
MIN_RECENTLY_SET_POLL_IGNORE_WINDOW_S: Final[float] = 5.0
MAX_RECENTLY_SET_POLL_IGNORE_WINDOW_S: Final[float] = 30.0

SELECT_SET_VALUE_DEBOUNCE_DELAY_S: Final = 0.5

COORDINATOR_FALLBACK_UPDATE_INTERVAL_MINUTES: Final[int] = 5
COORDINATOR_MAX_CONSECUTIVE_FAILURES_BEFORE_FALLBACK: Final[int] = 3

MIN_SCAN_INTERVAL: Final = 15
MAX_SCAN_INTERVAL: Final = 86430


# Polling Retry Mechanism (Non-Connection Errors)
POLLING_RETRY_INITIAL_DELAY_S: Final[float] = 60.0
POLLING_RETRY_MAX_DELAY_S: Final[float] = 300.0
POLLING_RETRY_BACKOFF_FACTOR: Final[float] = 2.0
POLLING_RETRY_MAX_ATTEMPTS: Final[int] = 5

# Set Value Retry Mechanism (now handled by ApiAccessManager)
SET_VALUE_RETRY_ATTEMPTS: Final[int] = 3
SET_VALUE_RETRY_DELAY_S: Final[float] = 2.0

NUMBER_SET_VALUE_DEBOUNCE_DELAY_S: Final = 3.0

# Service Definitions
SERVICE_GET_NODE_VALUE: Final = "get_node_value"
SERVICE_SET_NODE_VALUE: Final = "set_node_value"

ATTR_NODE_ID: Final = "node_id"
ATTR_VALUE: Final = "value"

# Diagnostics
DIAGNOSTICS_TO_REDACT_CONFIG_KEYS: Final = {CONF_HOST_IP}
DIAGNOSTICS_SENSITIVE_COORDINATOR_DATA_NODE_IDS: Final = {
    "20026",
    "20031",
    "20039",
}
DIAGNOSTICS_REDACTED_PLACEHOLDER: Final = "REDACTED"
