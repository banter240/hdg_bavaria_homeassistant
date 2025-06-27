"""Manages the dynamic creation of polling group structures from entity definitions.

This module contains the logic to read the `SENSOR_DEFINITIONS` from
`definitions.py` and dynamically build the `HDG_NODE_PAYLOADS` and
`POLLING_GROUP_ORDER` structures required by the data update coordinator.
This centralizes the definition of nodes and their polling groups in
`definitions.py`, adhering to the DRY principle.
"""

from __future__ import annotations

__version__ = "0.1.3"

import logging

from .classes.polling_group_manager import PollingGroupManager
from .const import DOMAIN, LIFECYCLE_LOGGER_NAME, POLLING_GROUP_DEFINITIONS
from .definitions import SENSOR_DEFINITIONS

_LOGGER = logging.getLogger(DOMAIN)
_LIFECYCLE_LOGGER = logging.getLogger(LIFECYCLE_LOGGER_NAME)


_polling_group_manager = PollingGroupManager(
    SENSOR_DEFINITIONS, POLLING_GROUP_DEFINITIONS
)

HDG_NODE_PAYLOADS = _polling_group_manager.hdg_node_payloads
POLLING_GROUP_ORDER = _polling_group_manager.polling_group_order
