"""
Manages data fetching and updates for the HDG Bavaria Boiler integration.

Coordinates periodic API calls, handles data parsing, and provides updates
to entities. Manages initial data population and error handling.
"""

import time

__version__ = "0.9.3"

import asyncio
import logging
import numbers
from datetime import timedelta, datetime
from typing import Any, Dict, List, Optional, Final

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.util import dt as dt_util

from .const import (
    DOMAIN,
    CONF_ENABLE_DEBUG_LOGGING,
    MIN_SCAN_INTERVAL as CONFIG_FLOW_MIN_SCAN_INTERVAL,
    DEFAULT_ENABLE_DEBUG_LOGGING,
)
from .polling_groups import (
    HDG_NODE_PAYLOADS,
    POLLING_GROUP_ORDER,
    NodeGroupPayload,
)
from .api import HdgApiClient, HdgApiConnectionError, HdgApiResponseError
from .utils import strip_hdg_node_suffix

_LOGGER = logging.getLogger(DOMAIN)

# Delay in seconds between fetching different polling groups sequentially during initial setup.
INITIAL_SEQUENTIAL_INTER_GROUP_DELAY_S: Final[float] = 2.0


class HdgDataUpdateCoordinator(DataUpdateCoordinator[Dict[str, Any]]):
    """
    Manages data fetching and updates for the HDG Bavaria Boiler integration.

    This coordinator employs a two-phase data fetching strategy:
    1. Initial full fetch: Sequentially retrieves data for all defined polling groups upon setup.
    2. Periodic updates: Fetches data only for polling groups that are due based on their configured scan intervals.
    """

    def __init__(
        self,
        hass: HomeAssistant,
        api_client: HdgApiClient,
        entry: ConfigEntry,
    ):
        """
        Initialize the HdgDataUpdateCoordinator.

        Args:
            hass: The Home Assistant instance.
            api_client: An instance of the HdgApiClient for API communication.
            entry: Config entry, used for user-configured options (scan intervals, host IP).
        """
        self.hass = hass
        self.api_client = api_client
        self.entry = entry

        current_config = self.entry.options or self.entry.data

        self.scan_intervals: Dict[str, timedelta] = {}
        # Validate that POLLING_GROUP_ORDER and HDG_NODE_PAYLOADS have matching keys.
        polling_group_set = set(POLLING_GROUP_ORDER)
        payloads_key_set = set(HDG_NODE_PAYLOADS.keys())
        if polling_group_set != payloads_key_set:
            missing_in_payloads = polling_group_set - payloads_key_set
            missing_in_polling = payloads_key_set - polling_group_set
            _LOGGER.error(
                "CRITICAL CONFIGURATION MISMATCH: POLLING_GROUP_ORDER and HDG_NODE_PAYLOADS keys do not match. "
                "This can lead to incorrect polling behavior or missing data. "
                "Missing in HDG_NODE_PAYLOADS (defined in POLLING_GROUP_ORDER but not HDG_NODE_PAYLOADS): %s; "
                "Missing in POLLING_GROUP_ORDER (defined in HDG_NODE_PAYLOADS but not POLLING_GROUP_ORDER): %s. "
                "Please check polling_groups.py.",
                missing_in_payloads or "None",
                missing_in_polling or "None",
            )
            # Specifically raise an error if groups intended for polling are not defined in payloads.
            if missing_in_payloads:
                raise ValueError(
                    f"CRITICAL CONFIG ERROR: The following groups are in POLLING_GROUP_ORDER but missing from HDG_NODE_PAYLOADS: {sorted(list(missing_in_payloads))}. "
                    "This prevents them from being polled. Please check polling_groups.py."
                )
            # Raise a hard error if there are groups in HDG_NODE_PAYLOADS missing from POLLING_GROUP_ORDER.
            if missing_in_polling:
                raise ValueError(
                    f"CRITICAL CONFIG ERROR: The following groups are in HDG_NODE_PAYLOADS but missing from POLLING_GROUP_ORDER: {sorted(list(missing_in_polling))}. "
                    "This prevents them from being polled. Please check polling_groups.py."
                )

        # Set up scan intervals, ensuring they meet the minimum defined in config_flow.
        for group_key, payload_details in HDG_NODE_PAYLOADS.items():
            config_key_for_scan = payload_details["config_key_scan_interval"]
            default_scan_val = payload_details["default_scan_interval"]
            raw_scan_val = current_config.get(config_key_for_scan, default_scan_val)

            try:
                scan_val_seconds_float = float(raw_scan_val)
                if scan_val_seconds_float < CONFIG_FLOW_MIN_SCAN_INTERVAL:
                    _LOGGER.warning(
                        f"Scan interval {scan_val_seconds_float}s for group '{group_key}' is below minimum {CONFIG_FLOW_MIN_SCAN_INTERVAL}s. "
                        f"Using default: {default_scan_val}s."
                    )
                    scan_val_seconds_float = float(default_scan_val)
            except (ValueError, TypeError):
                _LOGGER.warning(
                    f"Invalid scan interval '{raw_scan_val}' (type: {type(raw_scan_val).__name__}) for group '{group_key}'. "
                    f"Must be a number. Using default: {default_scan_val}s."
                )
                scan_val_seconds_float = float(default_scan_val)

            self.scan_intervals[group_key] = timedelta(seconds=scan_val_seconds_float)
        self._last_update_times: Dict[str, float] = {}
        self._initialize_last_update_times_monotonic()
        shortest_interval = (
            min(self.scan_intervals.values()) if self.scan_intervals else timedelta(seconds=60)
        )

        super().__init__(
            hass,
            _LOGGER,
            name=f"{DOMAIN} ({self.entry.title})",
            update_interval=shortest_interval,
        )
        self.data: Dict[str, Any] = {}
        _LOGGER.debug(
            f"HdgDataUpdateCoordinator for '{self.entry.title}' initialized. "
            f"Shortest interval: {shortest_interval}."
        )

    @property
    def enable_debug_logging(self) -> bool:
        """Return True if detailed debug logging for polling cycles is enabled."""
        if hasattr(self, "entry") and self.entry is not None:
            return (self.entry.options or {}).get(
                CONF_ENABLE_DEBUG_LOGGING, DEFAULT_ENABLE_DEBUG_LOGGING
            )
        return DEFAULT_ENABLE_DEBUG_LOGGING

    @property
    def last_update_times(self) -> Dict[str, float]:
        """Return the dictionary of last update times for polling groups."""
        return self._last_update_times

    def _initialize_last_update_times_monotonic(self) -> None:
        """
        Set initial 'last update time' for all polling groups to 0.0.

        This ensures they are fetched during the first refresh cycle.
        Uses `time.monotonic()` for consistent time tracking.
        """
        for group_key in POLLING_GROUP_ORDER:
            if group_key in self.scan_intervals:
                self._last_update_times[group_key] = 0.0
            else:
                # This case should ideally not happen if POLLING_GROUP_ORDER and HDG_NODE_PAYLOADS are consistent.
                _LOGGER.warning(
                    f"Polling group key '{group_key}' from POLLING_GROUP_ORDER not found in scan_intervals. "
                    f"Initialization of last update time will skip this group."
                )

    def _log_fetch_error_duration(
        self, group_key: str, error_type: str, start_time: float, error: Exception
    ) -> None:
        """
        Log error details along with the duration of the failed fetch attempt.

        This helper is invoked when `enable_debug_logging` is true to provide
        more context on fetch errors, including how long the attempt took before failing.
        """
        if self.enable_debug_logging:
            end_time_err = time.monotonic()
            duration = end_time_err - start_time
            _LOGGER.warning(
                f"{error_type.upper()} during fetch for group: {group_key} at {dt_util.as_local(dt_util.utcnow())}. "
                f"Duration: {duration:.2f}s. Error: {error}"
            )

    def _parse_and_store_api_items(
        self,
        group_key: str,
        api_items: List[Dict[str, Any]],
    ) -> List[Dict[str, Any]]:
        """
        Parse API items, validate, and store them in `self.data`.

        Strips suffixes from node IDs for consistent keys. Handles duplicates within
        a single group's response by keeping the first occurrence. `self.data` reflects
        the latest value for any node ID across all groups.

        Note: `self.data` is a central store. If the same base node ID is part of
        different polling groups (defined in HDG_NODE_PAYLOADS), the value in `self.data`
        for that base node ID will reflect the value from the most recent successful fetch
        of any group containing that base node ID.

        """
        successfully_processed_and_stored_items: List[Dict[str, Any]] = []
        # Tracks raw node IDs seen in this specific API call for this group to detect exact duplicates.
        raw_ids_seen_in_this_call: set[str] = set()
        # Tracks cleaned (base) node IDs processed in this call to detect functional duplicates.
        cleaned_node_ids_processed_this_call: set[str] = set()

        for item in api_items:
            api_id_value = item.get("id")
            node_id_with_suffix: str  # Processed ID, guaranteed to be string if valid

            if isinstance(api_id_value, str):
                node_id_with_suffix = api_id_value.strip()
                if not node_id_with_suffix:  # Check if empty after stripping
                    _LOGGER.warning(
                        f"API response for group '{group_key}' contains an item with an empty string 'id'. "
                        f"Item: {item}. Skipping this item."
                    )
                    continue
            elif isinstance(api_id_value, int):
                # Convert integer ID to string. Assumes integer IDs don't have suffixes like 'T'
                # and str(int) doesn't produce leading/trailing spaces.
                node_id_with_suffix = str(api_id_value)
            else:
                # Handles None or other unexpected types for 'id'
                _LOGGER.warning(
                    f"API response for group '{group_key}' contains an item with missing or invalid type for 'id' (expected int or str). "
                    f"Item: {item}. Skipping this item."
                )
                continue

            # At this point, node_id_with_suffix is a non-empty string.

            # First, check for exact raw ID duplicates from the API.
            if node_id_with_suffix in raw_ids_seen_in_this_call:
                _LOGGER.error(
                    f"Exact duplicate raw node ID '{node_id_with_suffix}' received in API response for group '{group_key}'. "
                    f"Item: {item}. This indicates a potential upstream API issue. This occurrence will be skipped."
                )
                continue
            raw_ids_seen_in_this_call.add(node_id_with_suffix)

            item_text_value = item.get("text")

            if item_text_value is None:
                _LOGGER.warning(
                    f"API response for group '{group_key}', node ID with suffix '{node_id_with_suffix}', "
                    f"is missing the 'text' key. Item: {item}. Skipping update for this node."
                )
                continue

            node_id_clean = strip_hdg_node_suffix(node_id_with_suffix)

            if node_id_clean in cleaned_node_ids_processed_this_call:
                existing_value = self.data.get(node_id_clean)
                if existing_value != item_text_value:
                    _LOGGER.critical(
                        f"Duplicate base node ID '{node_id_clean}' (from API ID '{node_id_with_suffix}') "
                        f"received in API response for group '{group_key}' WITH CONFLICTING VALUES. "
                        f"Existing (first occurrence): '{existing_value}', New (skipped): '{item_text_value}'. "
                        "This indicates a severe API data inconsistency. The first occurrence's value is kept, but data integrity is compromised."
                    )
                    raise UpdateFailed(
                        f"Critical API data inconsistency: Duplicate base node ID '{node_id_clean}' with conflicting values in group '{group_key}'. "
                        f"Existing: '{existing_value}', New: '{item_text_value}'."
                    )
                else:  # Values are identical
                    _LOGGER.debug(
                        f"Duplicate base node ID '{node_id_clean}' (from API ID '{node_id_with_suffix}') received in API response for group '{group_key}' with identical value '{item_text_value}'. Skipping."
                    )
                continue

            self.data[node_id_clean] = item_text_value
            cleaned_node_ids_processed_this_call.add(node_id_clean)
            successfully_processed_and_stored_items.append(item)
        return successfully_processed_and_stored_items

    async def _fetch_group_data(
        self, group_key: str, payload_config: NodeGroupPayload
    ) -> Optional[List[Dict[str, Any]]]:
        """
        Fetch data for a single polling group from the HDG API.

        Args:
            group_key: The key identifying the polling group.
            payload_config: The configuration for the polling group, including the API payload string.

        Returns:
            A list of successfully processed API items if the fetch was successful,
            or None if there was an API response error (but not a connection error).

        Raises:
            HdgApiConnectionError: If a connection error occurs during the API call.
        """
        payload_str = payload_config.get("payload_str")
        if payload_str is None:
            _LOGGER.error(
                f"Configuration error: 'payload_str' is missing in HDG_NODE_PAYLOADS for group_key '{group_key}'. "
                "This group cannot be fetched."
            )
            return None

        start_time_group_fetch = time.monotonic()
        if self.enable_debug_logging:
            _LOGGER.info(
                f"INITIATING FETCH for group: {group_key} at {dt_util.as_local(dt_util.utcnow())}"
            )
        try:
            fetched_data_list = await self.api_client.async_get_nodes_data(payload_str)

            if fetched_data_list is not None:  # API client returned data (could be an empty list)
                # Parse and store the fetched items.
                successfully_processed_items = self._parse_and_store_api_items(
                    group_key, fetched_data_list
                )
                _LOGGER.debug(
                    f"Successfully processed data for HDG group: {group_key}. {len(successfully_processed_items)} valid items processed."
                )
                end_time_group_fetch = time.monotonic()
                if self.enable_debug_logging:
                    _LOGGER.info(
                        f"COMPLETED FETCH for group: {group_key} at {dt_util.as_local(dt_util.utcnow())}. "
                        f"Duration: {end_time_group_fetch - start_time_group_fetch:.2f}s"
                    )
                return successfully_processed_items
            else:
                _LOGGER.warning(
                    f"Polling for group {group_key} returned None from api_client without raising an error. This indicates an unexpected issue."
                )  # pragma: no cover
                return None

        except HdgApiConnectionError as conn_err:
            self._log_fetch_error_duration(
                group_key, "Connection error", start_time_group_fetch, conn_err
            )
            raise
        except HdgApiResponseError as err:
            _LOGGER.warning(
                f"API response error polling group {group_key}: {err}. Data for this group may be stale."
            )  # pragma: no cover
            self._log_fetch_error_duration(
                group_key, "API response error", start_time_group_fetch, err
            )
            return None
        except Exception as err:
            _LOGGER.exception(
                f"Unexpected error polling group '{group_key}'. This error will be re-raised. Error: {err}"
            )
            raise

    async def async_config_entry_first_refresh(self) -> None:
        """
        Performs the initial sequential data refresh for all polling groups upon Home Assistant setup.
        """
        start_time_first_refresh = time.monotonic()
        if self.enable_debug_logging:
            _LOGGER.info(
                f"INITIATING async_config_entry_first_refresh for {self.name} at {dt_util.as_local(dt_util.utcnow())} with {INITIAL_SEQUENTIAL_INTER_GROUP_DELAY_S}s inter-group delay..."
            )
        any_group_failed_connection = False
        initial_data_items_fetched_count = 0

        for i, group_key in enumerate(POLLING_GROUP_ORDER):
            payload_config = HDG_NODE_PAYLOADS.get(group_key)
            if not payload_config:
                _LOGGER.warning(
                    f"Skipping initial poll for group '{group_key}': not defined in HDG_NODE_PAYLOADS."
                )  # pragma: no cover
                continue

            _LOGGER.debug(f"Initial sequential poll for group: {group_key}")
            try:
                processed_items = await self._fetch_group_data(group_key, payload_config)
                if processed_items is not None:  # Data fetched (could be empty list)
                    self._last_update_times[group_key] = time.monotonic()
                    initial_data_items_fetched_count += len(processed_items)
                    _LOGGER.debug(
                        f"Initial poll for group {group_key} successful, {len(processed_items)} items processed."
                    )
                else:
                    _LOGGER.warning(
                        f"Initial poll for group {group_key} reported failure (e.g., API response error)."
                    )  # pragma: no cover
            except HdgApiConnectionError as err:
                _LOGGER.warning(
                    f"Initial poll for group {group_key} failed with connection error: {err}"
                )
                any_group_failed_connection = True
            except Exception as err:
                _LOGGER.exception(
                    f"Unexpected error during initial poll of group {group_key}: {err}"
                )
                any_group_failed_connection = True  # pragma: no cover
            if payload_config and i < len(POLLING_GROUP_ORDER) - 1:
                _LOGGER.debug(
                    f"Waiting {INITIAL_SEQUENTIAL_INTER_GROUP_DELAY_S}s before polling next group."
                )
                await asyncio.sleep(INITIAL_SEQUENTIAL_INTER_GROUP_DELAY_S)
        if not self.data and any_group_failed_connection:
            _LOGGER.error(
                f"Initial data refresh for {self.name} failed to retrieve any data due to connection issues. "
                "Setup will be retried by Home Assistant."
            )
            raise UpdateFailed(
                "Failed to connect to HDG boiler during initial setup and retrieve any data."
            )
        if not self.data:
            _LOGGER.warning(
                f"Initial data refresh for {self.name} completed, but no data was fetched from any group. "
                "This might be normal if the boiler is offline or payloads are empty."  # pragma: no cover
            )

        end_time_first_refresh = time.monotonic()
        if self.enable_debug_logging:
            _LOGGER.info(
                f"COMPLETED async_config_entry_first_refresh for {self.name} at {dt_util.as_local(dt_util.utcnow())}. "
                f"Duration: {end_time_first_refresh - start_time_first_refresh:.2f}s. "
                f"Approx {initial_data_items_fetched_count} node values potentially updated. Total items in coordinator.data: {len(self.data or [])}"
            )
        self.async_set_updated_data(self.data)

    def _get_due_polling_groups(
        self, current_time_monotonic: float
    ) -> list[tuple[str, NodeGroupPayload]]:
        """
        Identify polling groups that are due for an update.

        Compares the current monotonic time against the last update time and scan
        interval for each polling group.

        Args:
            current_time_monotonic: The current time from `time.monotonic()`.

        Returns:
            A list of tuples, where each tuple contains the group key and its
            payload configuration for groups that are due for an update.
        """
        due_groups: list[tuple[str, NodeGroupPayload]] = []
        for group_key in POLLING_GROUP_ORDER:
            payload_config = HDG_NODE_PAYLOADS.get(group_key)

            if not payload_config or group_key not in self.scan_intervals:
                _LOGGER.debug(
                    f"Skipping group '{group_key}' in due check: not defined in HDG_NODE_PAYLOADS or scan_intervals."
                )  # pragma: no cover
                continue

            group_scan_interval_seconds = self.scan_intervals[group_key].total_seconds()
            last_update_time_for_group = self._last_update_times.get(group_key, 0.0)

            if (current_time_monotonic - last_update_time_for_group) >= group_scan_interval_seconds:
                due_groups.append((group_key, payload_config))
            else:
                _LOGGER.debug(
                    f"Skipping poll for HDG group: {group_key} (Next in approx. {max(0, group_scan_interval_seconds - (current_time_monotonic - last_update_time_for_group)):.0f}s)"
                )
        return due_groups

    async def _sequentially_fetch_due_groups_data(
        self, due_groups: list[tuple[str, NodeGroupPayload]]
    ) -> tuple[bool, bool]:
        """
        Sequentially fetch data for a list of due polling groups.

        Iterates through the provided list of due groups, fetching data for each one
        sequentially with a small delay between fetches. Handles API errors gracefully
        for individual groups, allowing other groups to still be attempted.

        Args:
            due_groups: A list of (group_key, payload_config) tuples for groups due for an update.

        Returns:
            A tuple (any_group_fetched_successfully, any_connection_error_encountered).
            Indicates if at least one group was fetched and if any connection errors occurred.
        """
        any_group_fetched_successfully = False
        any_connection_error_encountered = False

        for i, (group_key, payload_config) in enumerate(due_groups):
            _LOGGER.debug(
                f"Fetching data for due group: {group_key} (Index {i} of {len(due_groups)} due groups)"
            )
            try:
                processed_items = await self._fetch_group_data(group_key, payload_config)
                if processed_items is not None:  # Data fetched (could be empty list)
                    self._last_update_times[group_key] = time.monotonic()
                    any_group_fetched_successfully = True
            except HdgApiConnectionError as err:
                # Log connection error and continue with other groups
                _LOGGER.warning(
                    f"Connection error for group {group_key} during sequential fetch: {err}. "
                    "This group will be skipped in this cycle. Other due groups will still be attempted."
                )
                any_connection_error_encountered = True
            except Exception as err:
                _LOGGER.exception(
                    f"Unexpected error processing group {group_key} in _async_update_data. "
                    f"This group will be skipped in this cycle. Error: {err}"
                )

            if i < len(due_groups) - 1:  # If not the last group in the list
                _LOGGER.debug(
                    f"Waiting {INITIAL_SEQUENTIAL_INTER_GROUP_DELAY_S}s before polling next due group."
                )
                await asyncio.sleep(INITIAL_SEQUENTIAL_INTER_GROUP_DELAY_S)

        return any_group_fetched_successfully, any_connection_error_encountered

    async def _async_update_data(self) -> Dict[str, Any]:
        """
        Periodically called by DataUpdateCoordinator to fetch data for due polling groups.
        """
        start_time_update_cycle = time.monotonic()
        if self.enable_debug_logging:
            _LOGGER.info(
                f"INITIATING _async_update_data cycle at {dt_util.as_local(dt_util.utcnow())}"
            )
        current_time_for_due_check = time.monotonic()
        _LOGGER.debug(
            f"Coordinator _async_update_data cycle started at {datetime.fromtimestamp(current_time_for_due_check, tz=dt_util.get_default_time_zone())}"
        )

        # Identify which polling groups are due.
        due_groups_to_fetch = self._get_due_polling_groups(current_time_for_due_check)

        if not due_groups_to_fetch:
            _LOGGER.debug("No polling groups were due for an update in this coordinator cycle.")
            end_time_update_cycle_no_tasks = time.monotonic()
            if self.enable_debug_logging:
                _LOGGER.info(
                    f"COMPLETED _async_update_data cycle (no groups due) at {dt_util.as_local(dt_util.utcnow())}. "
                    f"Duration: {end_time_update_cycle_no_tasks - start_time_update_cycle:.3f}s"
                )
            return self.data

        _LOGGER.debug(f"Due groups to fetch: {[g[0] for g in due_groups_to_fetch]}")

        # Fetch data for due groups.
        (
            any_group_fetched_successfully,
            any_connection_error_encountered,
        ) = await self._sequentially_fetch_due_groups_data(due_groups_to_fetch)

        # Handle cases where no group was successfully fetched.
        if not any_group_fetched_successfully and due_groups_to_fetch:  # pragma: no cover
            if any_connection_error_encountered:
                _LOGGER.error(
                    "Failed to fetch data from HDG boiler for all due groups due to connection errors with one or more groups."
                )
                raise UpdateFailed(
                    "Failed to fetch data from HDG boiler due to connection errors with one or more groups."
                )
            else:
                _LOGGER.warning(
                    "Attempted to poll due groups, but no group updated successfully in this cycle (e.g., API errors for all groups). Data may be stale."
                )

        end_time_update_cycle_with_tasks = time.monotonic()
        if self.enable_debug_logging:
            _LOGGER.info(
                f"COMPLETED _async_update_data cycle (sequentially processed {len(due_groups_to_fetch)} due groups) at {dt_util.as_local(dt_util.utcnow())}. "
                f"Duration: {end_time_update_cycle_with_tasks - start_time_update_cycle:.3f}s"
            )
        return self.data

    async def async_update_internal_node_state(self, node_id: str, new_value: Any) -> None:
        """
        Update a node's value in the internal data store and notify listeners.
        Called after a successful API set operation to reflect changes immediately.

        Args:
            node_id: Base HDG node ID (no suffix).
            new_value: New value for the node. Expected to be a string.
        """
        if self.data.get(node_id) != new_value:
            self.data[node_id] = new_value  # new_value is already a string
            _LOGGER.debug(
                f"Internal state for node '{node_id}' updated to '{new_value}'. Notifying listeners."
            )
            self.async_set_updated_data(self.data)
        else:
            _LOGGER.debug(
                f"Internal state for node '{node_id}' already '{new_value}'. No update notification."
            )

    async def async_set_node_value_if_changed(
        self, node_id: str, new_value_to_set: Any, entity_name_for_log: str = "Unknown Entity"
    ) -> bool:
        """
        Set a node value via the API if it's different from the current known value.
        Updates internal state on success. Used by number entities and services.
        Validates type and compares normalized values before calling the API.
        """
        if not isinstance(new_value_to_set, (numbers.Number, bool, str)):
            _LOGGER.error(
                f"Unsupported type for new_value_to_set: {type(new_value_to_set).__name__} for node '{entity_name_for_log}' (ID: {node_id})."
            )
            raise TypeError(
                f"Unsupported type for new_value_to_set: {type(new_value_to_set).__name__}. Only int, float, bool, and str are allowed."
            )
        api_value_to_send_str = str(new_value_to_set)

        def _normalize_for_comparison(val: Any) -> Any:
            """
            Normalize a value for robust comparison.
            Converts various input types to a consistent type (Python bool, int, float,
            or original string if not convertible) to avoid false negatives during
            "if_changed" checks due to type or formatting differences.

            Handles:
            - Actual Python booleans, integers, and floats directly.
            - String representations:
                - "true"/"false" (case-insensitive) become Python booleans.
                - Numeric strings (e.g., "0", "1", "10.0", "-5.5") are converted to `int` or `float`.
                  If a float string represents a whole number (e.g., "10.0"), it's converted to `int`.
            - Other types (e.g., None) or unconvertible strings are returned as is (after stripping for strings).
            Localized boolean/numeric strings (e.g., "wahr", "1,0") are NOT explicitly handled.
            """
            if isinstance(val, bool):
                return val
            elif isinstance(val, (int, float)):
                return val
            elif isinstance(val, str):
                val_stripped = val.strip()
                if val_stripped.lower() == "true":
                    return True
                elif val_stripped.lower() == "false":
                    return False
                else:
                    try:
                        float_val = float(val_stripped)
                        return int(float_val) if float_val == int(float_val) else float_val
                    except ValueError:
                        _LOGGER.debug(
                            f"Value '{val_stripped}' could not be normalized to a number in _normalize_for_comparison for node '{node_id}'."
                        )
                        return val_stripped
            else:
                return val

        current_known_raw_value = self.data.get(node_id)
        normalized_current_value = _normalize_for_comparison(current_known_raw_value)
        normalized_new_value = _normalize_for_comparison(new_value_to_set)

        if current_known_raw_value is not None and normalized_current_value == normalized_new_value:
            _LOGGER.info(
                f"Coordinator: Value for node '{entity_name_for_log}' (ID: {node_id}) is already '{api_value_to_send_str}'. Skipping API call."
            )
            return True

        success = await self.api_client.async_set_node_value(node_id, api_value_to_send_str)
        if success:
            _LOGGER.info(
                f"Coordinator: Successfully set node '{entity_name_for_log}' (ID: {node_id}) to '{api_value_to_send_str}' via API."
            )
            await self.async_update_internal_node_state(node_id, api_value_to_send_str)
            return True
        else:
            _LOGGER.error(
                f"Coordinator: API call to set node '{entity_name_for_log}' (ID: {node_id}) to '{api_value_to_send_str}' reported failure."
            )
            return False
