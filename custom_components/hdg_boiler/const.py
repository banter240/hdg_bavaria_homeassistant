"""
Constants for the HDG Bavaria Boiler integration.

This module centralizes all constants used across the HDG Bavaria Boiler
integration. Constants are grouped by their functional area, such as core
integration details, API communication, data interpretation, configuration,
polling behavior, service definitions, and diagnostics.
Entity-specific definitions (SENSOR_DEFINITIONS) are managed in `definitions.py`.
"""

__version__ = "0.9.28"

from typing import Final

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
# Constants related to interacting with the HDG Boiler's API.

# --- API Endpoints ---
API_ENDPOINT_DATA_REFRESH: Final = "/ApiManager.php?action=dataRefresh"
API_ENDPOINT_SET_VALUE: Final = "/ActionManager.php?action=set_value_changed"

# --- API Timeouts (seconds) ---
API_TIMEOUT: Final = 30  # Default timeout for general API calls.
CONFIG_FLOW_API_TIMEOUT: Final = 15  # Shorter timeout for config flow connectivity check.

# ============================================================================
# API Data Interpretation
# ============================================================================
# Constants for understanding and processing data received from the API.

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
# Keys and default values used in Home Assistant config entries and options flows.

# --- Configuration Keys (used in entry.data and entry.options) ---
CONF_DEVICE_ALIAS: Final = "device_alias"
CONF_ENABLE_DEBUG_LOGGING: Final = "enable_debug_logging"
CONF_HOST_IP: Final = "host_ip"
CONF_SCAN_INTERVAL_GROUP1: Final = "scan_interval_realtime_core"
CONF_SCAN_INTERVAL_GROUP2: Final = "scan_interval_status_general"
CONF_SCAN_INTERVAL_GROUP3: Final = "scan_interval_config_counters_1"
CONF_SCAN_INTERVAL_GROUP4: Final = "scan_interval_config_counters_2"
CONF_SCAN_INTERVAL_GROUP5: Final = "scan_interval_config_counters_3"
CONF_SOURCE_TIMEZONE: Final = "source_timezone"

# --- Default Configuration Values ---
DEFAULT_ENABLE_DEBUG_LOGGING: Final = False
DEFAULT_HOST_IP: Final = ""  # Must be provided by the user.
DEFAULT_SOURCE_TIMEZONE: Final = "Europe/Berlin"  # For parsing datetimes from the boiler.

# Default scan intervals for polling groups (in seconds).
# These are staggered to distribute API load.
DEFAULT_SCAN_INTERVAL_GROUP1: Final = 15  # Group 1: Core real-time data.
DEFAULT_SCAN_INTERVAL_GROUP2: Final = 304  # Group 2: General status data (approx. 5 mins).
DEFAULT_SCAN_INTERVAL_GROUP3: Final = 86410  # Group 3: Config/Counters 1 (approx. 24 hours).
DEFAULT_SCAN_INTERVAL_GROUP4: Final = 86420  # Group 4: Config/Counters 2 (approx. 24 hours).
DEFAULT_SCAN_INTERVAL_GROUP5: Final = 86430  # Group 5: Config/Counters 3 (approx. 24 hours).

# ============================================================================
# Polling & Update Behavior
# ============================================================================
# Constants controlling how the coordinator fetches and processes data.

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

# ============================================================================
# Set Value Worker Retry Mechanism
# ============================================================================
# Constants for the retry logic in the `_set_value_worker`.

SET_VALUE_RETRY_MAX_ATTEMPTS: Final[int] = 3  # Max number of retries for a failed set operation.
SET_VALUE_RETRY_BASE_BACKOFF_S: Final[float] = 2.0  # Initial backoff delay in seconds for retries.

# ============================================================================
# UI & Entity Behavior
# ============================================================================
# Constants influencing user interface elements and entity behavior.

# Minimum scan interval allowed in options flow (seconds).
MIN_SCAN_INTERVAL: Final = 15
# Maximum scan interval allowed in options flow (seconds, approx. 24 hours).
MAX_SCAN_INTERVAL: Final = 86430

# Debounce delay for setting number entity values via API (seconds).
# Prevents API flooding from rapid UI changes for number entities.
NUMBER_SET_VALUE_DEBOUNCE_DELAY_S: Final = 3.0

# ============================================================================
# Service Definitions
# ============================================================================
# Constants related to custom services provided by the integration.

# --- Service Names ---
SERVICE_GET_NODE_VALUE: Final = "get_node_value"
SERVICE_SET_NODE_VALUE: Final = "set_node_value"

# --- Service Attribute Names ---
ATTR_NODE_ID: Final = "node_id"
ATTR_VALUE: Final = "value"

# ============================================================================
# Diagnostics
# ============================================================================
# Constants for generating and redacting diagnostic information.

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
