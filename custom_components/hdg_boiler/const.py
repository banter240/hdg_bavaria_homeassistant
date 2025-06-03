"""
Constants for the HDG Bavaria Boiler integration.

This file centralizes constants used throughout the HDG Bavaria Boiler integration,
including domain information, API endpoints, configuration keys, default values,
service definitions, and other shared values. Entity-specific definitions
(SENSOR_DEFINITIONS) are maintained in `definitions.py`.
"""

__version__ = "0.9.21"

from typing import Final

# --- Core Integration Constants ---
DOMAIN: Final = "hdg_boiler"  # Domain of the integration.
DEFAULT_NAME: Final = "HDG Boiler"  # Default name for the device in Home Assistant.
MANUFACTURER: Final = "HDG Bavaria GmbH"  # Manufacturer for HA device registry.
MODEL_PREFIX: Final = (
    "HDG"  # Used for HA device model if specific model cannot be determined from API.
)

# --- HDG API Specific Values ---
# Strings from the HDG API indicating unavailable or invalid data.
# Lowercase for case-insensitive comparison.
HDG_UNAVAILABLE_STRINGS: Final[set[str]] = {"---", "unavailable", "none", "n/a"}
# Special text from HDG API for datetimes representing "more than 7 days ago".
HDG_DATETIME_SPECIAL_TEXT: Final = "größer 7 tage"
# Known suffixes for HDG API nodes that are settable.
KNOWN_HDG_API_SETTER_SUFFIXES: Final = "TUVWXY"

# --- API Communication Parameters ---
API_ENDPOINT_DATA_REFRESH: Final = "/ApiManager.php?action=dataRefresh"
API_ENDPOINT_SET_VALUE: Final = "/ActionManager.php?action=set_value_changed"
API_TIMEOUT: Final = 30  # Default timeout in seconds for API requests.
CONFIG_FLOW_API_TIMEOUT: Final = 15  # Shorter timeout for config flow connectivity check.

# --- Configuration Keys (Config Flow & Options Flow) ---
CONF_DEVICE_ALIAS: Final = "device_alias"
CONF_ENABLE_DEBUG_LOGGING: Final = "enable_debug_logging"
CONF_HOST_IP: Final = "host_ip"
CONF_SCAN_INTERVAL_GROUP1: Final = "scan_interval_realtime_core"
CONF_SCAN_INTERVAL_GROUP2: Final = "scan_interval_status_general"
CONF_SCAN_INTERVAL_GROUP3: Final = "scan_interval_config_counters_1"
CONF_SCAN_INTERVAL_GROUP4: Final = "scan_interval_config_counters_2"
CONF_SCAN_INTERVAL_GROUP5: Final = "scan_interval_config_counters_3"
CONF_ENABLE_DEBUG_LOGGING: Final = "enable_debug_logging"
CONF_SOURCE_TIMEZONE: Final = "source_timezone"  # Added for timezone configuration
DEFAULT_HOST_IP: Final = ""  # Default value for host IP if not provided.

# --- Default Configuration Values ---
DEFAULT_ENABLE_DEBUG_LOGGING: Final = False
DEFAULT_SOURCE_TIMEZONE: Final = "Europe/Berlin"  # Added for timezone configuration

# Default scan intervals for polling groups (in seconds).
# These are staggered to distribute API load.
DEFAULT_SCAN_INTERVAL_GROUP1: Final = 15  # Group 1: Core real-time data.
DEFAULT_SCAN_INTERVAL_GROUP2: Final = 304  # Group 2: General status data (approx. 5 mins).
DEFAULT_SCAN_INTERVAL_GROUP3: Final = 86410  # Group 3: Config/Counters (approx. 24 hours).
DEFAULT_SCAN_INTERVAL_GROUP4: Final = 86420  # Group 4: Config/Counters (approx. 24 hours).
DEFAULT_SCAN_INTERVAL_GROUP5: Final = 86430  # Group 5: Config/Counters (approx. 24 hours).

# --- UI & Entity Behavior Parameters ---
# Minimum scan interval allowed in options flow (seconds).
MIN_SCAN_INTERVAL: Final = 15
# Maximum scan interval allowed in options flow (seconds, approx. 24 hours).
MAX_SCAN_INTERVAL: Final = 86430
# Debounce delay for setting number entity values via API (seconds).
# Prevents API flooding from rapid UI changes.
NUMBER_SET_VALUE_DEBOUNCE_DELAY_S: Final = 2.0

# --- Service Definitions ---
SERVICE_SET_NODE_VALUE: Final = "set_node_value"
SERVICE_GET_NODE_VALUE: Final = "get_node_value"

# Attribute names used in service calls.
ATTR_NODE_ID: Final = "node_id"
ATTR_VALUE: Final = "value"

# --- Diagnostics Specific Constants ---
# Configuration keys to redact in diagnostics output.
DIAGNOSTICS_TO_REDACT_CONFIG_KEYS: Final = {CONF_HOST_IP}
# Sensitive node IDs in coordinator data to redact in diagnostics.
DIAGNOSTICS_SENSITIVE_COORDINATOR_DATA_NODE_IDS: Final = {
    "20026",  # anlagenbezeichnung_sn (Boiler Serial Number)
    "20031",  # mac_adresse (MAC Address)
    "20039",  # hydraulikschema_nummer (Hydraulic Scheme Number)
}
# Placeholder string for redacted values in diagnostics.
DIAGNOSTICS_REDACTED_PLACEHOLDER: Final = "REDACTED"
