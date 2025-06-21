"""Constants for the HDG Bavaria Boiler integration.

This module centralizes all constants used across the HDG Bavaria Boiler
integration. Constants are grouped by their functional area, such as core
integration details, API communication parameters, data interpretation rules,
configuration keys and defaults, polling and update behavior controls,
service definitions, and diagnostic settings.

Entity-specific definitions (e.g., `SENSOR_DEFINITIONS`) are managed in `definitions.py`,
and enumeration mappings (e.g., `HDG_ENUM_MAPPINGS`) are in `enums.py`.
"""

__version__ = "0.9.33"

from typing import Final

from .models import PollingGroupStaticDefinition

# ============================================================================
# Core Integration Constants
# ============================================================================
# These constants define fundamental properties of the integration.

DOMAIN: Final = "hdg_boiler"
DEFAULT_NAME: Final = "HDG Boiler"  # Default name for the device in Home Assistant.
MANUFACTURER: Final = "HDG Bavaria GmbH"  # Manufacturer for HA device registry.
MODEL_PREFIX: Final = "HDG"  # Prefix for HA device model if not available from API.

# ============================================================================
# API Communication
# ============================================================================
# Constants defining how the integration interacts with the HDG Boiler's web API,
# including endpoint paths and timeout values.

# --- API Endpoints ---
API_ENDPOINT_DATA_REFRESH: Final = "/ApiManager.php?action=dataRefresh"
API_ENDPOINT_SET_VALUE: Final = "/ActionManager.php?action=set_value_changed"
CONFIG_FLOW_TEST_PAYLOAD: Final = "nodes=1T-2T-3T-4T"

# --- API Timeouts (seconds) ---
API_TIMEOUT: Final = 30  # Default timeout for general API calls.
CONFIG_FLOW_API_TIMEOUT: Final = (
    15  # Shorter timeout for config flow connectivity check.
)

# ============================================================================
# API Data Interpretation
# ============================================================================
# Constants that aid in understanding and processing data received from the
# HDG Boiler API, such as markers for unavailable data or known node ID suffixes.

# Known string values from the HDG API that indicate unavailable or invalid data.
# Used for availability checks. Compared case-insensitively.
HDG_UNAVAILABLE_STRINGS: Final[set[str]] = {"---", "unavailable", "none", "n/a"}

# Special text from the HDG API used in datetime fields to indicate
# a time more than 7 days in the past.
HDG_DATETIME_SPECIAL_TEXT: Final = "größer 7 tage"

# Known suffixes appended to HDG API node IDs (e.g., "1234T", "5678U").
# These often indicate the data type or if the node is settable.
KNOWN_HDG_API_SETTER_SUFFIXES: Final[set[str]] = {"T", "U", "V", "W", "X", "Y"}

# ============================================================================
# Configuration & Options Flow
# ============================================================================
# Defines keys for configuration entries (both `data` and `options`) and their
# default values, used during initial setup and subsequent option adjustments.

# --- General Configuration Keys (used in entry.data and entry.options) ---
CONF_DEVICE_ALIAS: Final = "device_alias"
CONF_ENABLE_DEBUG_LOGGING: Final = "enable_debug_logging"
CONF_HOST_IP: Final = "host_ip"
CONF_SOURCE_TIMEZONE: Final = "source_timezone"

# --- Default Configuration Values ---
DEFAULT_ENABLE_DEBUG_LOGGING: Final = (
    False  # Default for enabling detailed polling logs.
)
DEFAULT_HOST_IP: Final = ""  # Must be provided by the user.
DEFAULT_SOURCE_TIMEZONE: Final = (
    "Europe/Berlin"  # For parsing datetimes from the boiler.
)

# Central definition of all polling groups and their static properties.
# This list is the single source of truth for polling group configuration.
# The order in this list defines the processing order.
POLLING_GROUP_DEFINITIONS: Final[list[PollingGroupStaticDefinition]] = [
    {
        "key": "group_1",  # Used in definitions.py and internally
        "name": "Realtime Core",
        "config_key": "scan_interval_group_1_realtime_core",
        "default_interval": 15,
    },
    {
        "key": "group_2",
        "name": "General Status",
        "config_key": "scan_interval_group_2_status_general",
        "default_interval": 304,
    },
    {
        "key": "group_3",
        "name": "Config/Counters 1",
        "config_key": "scan_interval_group_3_config_counters_1",
        "default_interval": 86410,
    },
    {
        "key": "group_4",
        "name": "Config/Counters 2",
        "config_key": "scan_interval_group_4_config_counters_2",
        "default_interval": 86420,
    },
    {
        "key": "group_5",
        "name": "Config/Counters 3",
        "config_key": "scan_interval_group_5_config_counters_3",
        "default_interval": 86430,
    },
]

# ============================================================================
# Polling & Update Behavior
# ============================================================================
# Constants that control the behavior of the `HdgDataUpdateCoordinator`,
# including polling intervals, inter-group delays, and dynamic adjustments.

# Delay in seconds between fetching different polling groups sequentially,
# especially during initial setup or when multiple groups are due.
INITIAL_SEQUENTIAL_INTER_GROUP_DELAY_S: Final[float] = 2.0

# Timeout in seconds for the polling mechanism to acquire the API lock.
# If a set operation holds the lock for too long, polling might skip that cycle for the group.
POLLING_API_LOCK_TIMEOUT_S: Final[float] = 10.0

# Cooldown period in seconds after a successful 'set_node_value' API call
# before the next set operation from the queue is processed by the worker.
SET_NODE_COOLDOWN_S: Final = 2.0

# Maximum size of the set_value queue.
# Prevents unbounded memory usage if API calls fail repeatedly or the worker is backlogged.
SET_VALUE_QUEUE_MAX_SIZE: Final[int] = 50

# Time window (seconds) to ignore polled data for a node after it has been set via API.
# Helps prevent recently set values from being overwritten by a slightly delayed poll response.
RECENTLY_SET_POLL_IGNORE_WINDOW_S: Final[float] = 10.0

# --- Coordinator Dynamic Polling Interval Adjustment ---
# These constants manage how the coordinator adjusts its update interval
# based on API communication success or failure.
COORDINATOR_FALLBACK_UPDATE_INTERVAL_MINUTES: Final[int] = 5
COORDINATOR_MAX_CONSECUTIVE_FAILURES_BEFORE_FALLBACK: Final[int] = 3

# --- Scan Interval Limits for Options Flow ---

# Minimum scan interval allowed in options flow (seconds). Used also by coordinator.
MIN_SCAN_INTERVAL: Final = 15
# Maximum scan interval allowed in options flow (seconds, approx. 24 hours).
MAX_SCAN_INTERVAL: Final = 86430


# ============================================================================
# Set Value Worker Retry Mechanism
# ============================================================================
# Constants governing the retry logic for the `HdgSetValueWorker` when
# API calls to set values on the boiler fail.

SET_VALUE_RETRY_MAX_ATTEMPTS: Final[int] = (
    3  # Max number of retries for a failed set operation.
)
SET_VALUE_RETRY_BASE_BACKOFF_S: Final[float] = (
    2.0  # Initial backoff delay in seconds for retries.
)
SET_VALUE_CONNECTION_ERROR_RETRY_MULTIPLIER: Final[int] = (
    5  # Multiplier for max attempts on connection errors.
)
SET_VALUE_CONNECTION_ERROR_BACKOFF_MULTIPLIER: Final[float] = (
    2.0  # Multiplier for base backoff on connection errors.
)
SET_VALUE_MAX_INDIVIDUAL_BACKOFF_S: Final[float] = (
    300.0  # Max backoff for a single retry.
)

# Debounce delay for setting number entity values via API (seconds).
# Prevents API flooding from rapid UI changes for number entities.
NUMBER_SET_VALUE_DEBOUNCE_DELAY_S: Final = 3.0

# ============================================================================
# Service Definitions
# ============================================================================
# Constants defining the names and attributes for custom services exposed
# by the integration (e.g., `set_node_value`, `get_node_value`).

# --- Service Names ---
SERVICE_GET_NODE_VALUE: Final = "get_node_value"
SERVICE_SET_NODE_VALUE: Final = "set_node_value"

# --- Service Attribute Names ---
ATTR_NODE_ID: Final = "node_id"
ATTR_VALUE: Final = "value"

# ============================================================================
# Diagnostics
# ============================================================================
# Constants used in the generation and redaction of diagnostic information
# to aid in troubleshooting while protecting sensitive data.

# Configuration keys to redact in diagnostics output.
DIAGNOSTICS_TO_REDACT_CONFIG_KEYS: Final = {CONF_HOST_IP}

# Sensitive node IDs in coordinator data to redact in diagnostics.
# These typically contain personally identifiable or device-specific information.
DIAGNOSTICS_SENSITIVE_COORDINATOR_DATA_NODE_IDS: Final = {
    "20026",  # anlagenbezeichnung_sn (Boiler Serial Number)
    "20031",  # mac_adresse (MAC Address)
    "20039",  # hydraulikschema_nummer (Hydraulic Scheme Number)
}

# Placeholder string for redacted values in diagnostics.
DIAGNOSTICS_REDACTED_PLACEHOLDER: Final = "REDACTED"
