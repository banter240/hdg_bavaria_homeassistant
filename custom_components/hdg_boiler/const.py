"""
Constants for the HDG Bavaria Boiler integration.

This file defines shared constants and type definitions used across the integration.
Core entity definitions (SENSOR_DEFINITIONS) are located in 'definitions.py'.
"""

__version__ = "0.9.18"

from typing import Final

# These specific string values from the HDG API indicate that the node's data
# is not currently available or represents an invalid/uninitialized state.
# All entries must be lowercase for consistent, case-insensitive comparison.
HDG_UNAVAILABLE_STRINGS: Final[set[str]] = {"---", "unavailable", "none", "n/a"}
# Special phrase from HDG API for "greater than 7 days", used for non-datetime states.
HDG_DATETIME_SPECIAL_TEXT: Final = "größer 7 tage"

DOMAIN: Final = "hdg_boiler"  # Domain of the integration.
# Configuration defaults
DEFAULT_HOST_IP: Final = ""
DEFAULT_NAME: Final = "HDG Boiler"

# API Communication
API_ENDPOINT_DATA_REFRESH: Final = "/ApiManager.php?action=dataRefresh"
API_ENDPOINT_SET_VALUE: Final = "/ActionManager.php?action=set_value_changed"
API_TIMEOUT: Final = 30  # seconds

# Keys for Config Flow and Options Flow
CONF_HOST_IP: Final = "host_ip"
CONF_DEVICE_ALIAS: Final = "device_alias"
CONF_SCAN_INTERVAL_GROUP1: Final = "scan_interval_realtime_core"
CONF_SCAN_INTERVAL_GROUP2: Final = "scan_interval_status_general"
CONF_SCAN_INTERVAL_GROUP3: Final = "scan_interval_config_counters_1"
CONF_SCAN_INTERVAL_GROUP4: Final = "scan_interval_config_counters_2"
CONF_SCAN_INTERVAL_GROUP5: Final = "scan_interval_config_counters_3"
CONF_ENABLE_DEBUG_LOGGING: Final = "enable_debug_logging"
CONF_SOURCE_TIMEZONE: Final = "source_timezone"  # Added for timezone configuration

# Default scan intervals for polling groups in seconds
# Group 1: Core real-time data.
DEFAULT_SCAN_INTERVAL_GROUP1: Final = 15

# Group 2: General status data. Staggered to desynchronize from Group 1.
DEFAULT_SCAN_INTERVAL_GROUP2: Final = 304  # Approx. 5 minutes

# Groups 3-5: Configuration and less frequent counters. Staggered daily polls.
DEFAULT_SCAN_INTERVAL_GROUP3: Final = 86410  # Approx. 24 hours
DEFAULT_SCAN_INTERVAL_GROUP4: Final = 86420  # Approx. 24 hours
DEFAULT_SCAN_INTERVAL_GROUP5: Final = 86430  # Approx. 24 hours

DEFAULT_ENABLE_DEBUG_LOGGING: Final = False
DEFAULT_SOURCE_TIMEZONE: Final = "Europe/Berlin"  # Added for timezone configuration

# Debounce delay in seconds for setting number entity values via API.
# This helps prevent API flooding if a user rapidly changes a number input.
NUMBER_SET_VALUE_DEBOUNCE_DELAY_S: Final = 2.0

# Defines the absolute minimum scan interval (in seconds) allowed in the options flow.
# This value is based on the shortest default scan interval (DEFAULT_SCAN_INTERVAL_GROUP1).
MIN_SCAN_INTERVAL: Final = 15
# Defines the absolute maximum scan interval (in seconds) allowed in the options flow.
# This value is based on the longest default scan interval (DEFAULT_SCAN_INTERVAL_GROUP5), approximately 24 hours.
MAX_SCAN_INTERVAL: Final = 86430


# Service names
SERVICE_SET_NODE_VALUE: Final = "set_node_value"
SERVICE_GET_NODE_VALUE: Final = "get_node_value"

# Attribute names for service calls
ATTR_NODE_ID: Final = "node_id"
ATTR_VALUE: Final = "value"

# Fixed device information for HA device registry
MANUFACTURER: Final = "HDG Bavaria GmbH"
MODEL_PREFIX: Final = "HDG"  # Used if specific model cannot be determined from API
