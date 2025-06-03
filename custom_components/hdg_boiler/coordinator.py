"""
Manages data fetching and updates for the HDG Bavaria Boiler integration.

This module contains the `HdgDataUpdateCoordinator`, responsible for fetching
data from the HDG boiler API, managing the update schedule for different
data groups, processing the received data, and handling requests to set values.
"""

__version__ = "0.10.9"

import asyncio
import logging
import time

from datetime import timedelta
from typing import (
    Any,
    Dict,
    List,
    Optional,
)

import async_timeout

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.util import dt as dt_util

from .const import (
    DOMAIN,
    CONF_ENABLE_DEBUG_LOGGING,
    MIN_SCAN_INTERVAL as CONFIG_FLOW_MIN_SCAN_INTERVAL,
    SET_NODE_COOLDOWN_S,
    INITIAL_SEQUENTIAL_INTER_GROUP_DELAY_S,
    POLLING_API_LOCK_TIMEOUT_S,
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


class HdgDataUpdateCoordinator(DataUpdateCoordinator[Dict[str, Any]]):
    """
    Coordinates data updates and set value operations for the HDG Bavaria Boiler.

    This coordinator:
    - Manages periodic polling of different data groups based on configured intervals.
    - Handles requests to set node values via a dedicated background worker task.
    - Implements a two-phase data fetching strategy:
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

        Sets up scan intervals based on configuration, initializes internal state
        for tracking updates and pending set requests, and prepares the API client.

        Args:
            hass: The Home Assistant instance.
                  Used for creating tasks and accessing the event loop.
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
            missing_in_order = payloads_key_set - polling_group_set
            _LOGGER.error(
                "CRITICAL CONFIGURATION MISMATCH: POLLING_GROUP_ORDER and HDG_NODE_PAYLOADS keys do not match. "
                "This can lead to incorrect polling behavior or missing data. "
                "Missing in HDG_NODE_PAYLOADS (defined in POLLING_GROUP_ORDER but not HDG_NODE_PAYLOADS): %s; "
                "Missing in POLLING_GROUP_ORDER (defined in HDG_NODE_PAYLOADS but not POLLING_GROUP_ORDER): %s. "
                "Please check polling_groups.py.",
                missing_in_payloads or "None",
                missing_in_order or "None",
            )
            if missing_in_payloads:
                raise ValueError(
                    f"CRITICAL CONFIG ERROR: The following groups are in POLLING_GROUP_ORDER but missing from HDG_NODE_PAYLOADS: {sorted(list(missing_in_payloads))}. "
                    "This prevents them from being polled. Please check polling_groups.py."
                )
            if missing_in_order:
                raise ValueError(
                    f"CRITICAL CONFIG ERROR: The following groups are in HDG_NODE_PAYLOADS but missing from POLLING_GROUP_ORDER: {sorted(list(missing_in_order))}. "
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
        self._api_lock = asyncio.Lock()

        # Stores the latest value to be set for each node_id, replacing the asyncio.Queue.
        self._pending_set_values: Dict[str, tuple[str, str]] = {}
        self._pending_set_values_lock = asyncio.Lock()
        self._new_set_value_event = asyncio.Event()
        self._set_value_worker_task: Optional[asyncio.Task] = None

        # Tracks when a node was last set to prevent stale polling data overwriting recent changes.
        self._last_set_times: Dict[str, float] = {}

        _LOGGER.debug(
            f"HdgDataUpdateCoordinator for '{self.entry.title}' initialized. "
            f"Polling update interval set to shortest group interval: {shortest_interval}."
        )

    @property
    def enable_debug_logging(self) -> bool:
        """Return True if detailed debug logging for polling cycles is enabled."""
        return (self.entry.options or {}).get(
            CONF_ENABLE_DEBUG_LOGGING, DEFAULT_ENABLE_DEBUG_LOGGING
        )

    @property
    def last_update_times_public(
        self,
    ) -> Dict[str, float]:
        """Return the dictionary of last update times for polling groups."""
        return self._last_update_times

    def _initialize_last_update_times_monotonic(self) -> None:
        """
        Set the initial 'last update time' for all defined polling groups to 0.0.
        This ensures they are fetched during the first refresh cycle.
        """
        for group_key in POLLING_GROUP_ORDER:
            if group_key in self.scan_intervals:
                self._last_update_times[group_key] = 0.0
            else:
                _LOGGER.warning(
                    f"Polling group key '{group_key}' from POLLING_GROUP_ORDER not found in scan_intervals. "
                    f"Initialization of last update time will skip this group."
                )

    def _log_fetch_error_duration(
        self, group_key: str, error_type: str, start_time: float, error: Exception
    ) -> None:
        """Log error details along with the duration of the failed fetch attempt."""
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
        polling_start_time_monotonic: float,
    ) -> List[Dict[str, Any]]:
        """
        Parse API items, validate, store them in `self.data`, and handle duplicates.

        Skips updating from polling if a node was set more recently via API.
        This method iterates through items from an API response for a specific polling group.
        For each item:
        - It validates the presence and type of 'id' and 'text' fields.
        - It checks for duplicate raw node IDs within the same API call.
        - It strips any known suffix (T, U, V, etc.) from the node ID to get a clean ID.
        - It checks if the node was set via an API call more recently than the start
          of the current polling cycle. If so, the polled value is skipped to prevent
          overwriting a fresh user-set value with potentially stale polled data.
        - It checks for duplicate *cleaned* node IDs within the same API call. If a
          duplicate cleaned ID is found with a different value, a critical error is logged.
          If the value is the same, it's logged as a debug message and skipped.
        - Valid, non-duplicate, and not recently-set items are stored in `self.data`.

        Args:
            group_key: Key of the polling group being processed (for logging).
            api_items: List of dictionaries, where each dictionary is an item from the API response.
            polling_start_time_monotonic: Monotonic time when the current polling cycle started.
                                          Used to determine if a node was set more recently.

        Returns:
            A list of successfully processed and stored items (dictionaries).
        """
        successfully_processed_and_stored_items: List[Dict[str, Any]] = []
        raw_ids_seen_in_this_call: set[str] = set()
        cleaned_node_ids_processed_this_call: set[str] = set()

        for item in api_items:
            api_id_value = item.get("id")
            node_id_with_suffix: str

            if isinstance(api_id_value, str):
                node_id_with_suffix = api_id_value.strip()
                if not node_id_with_suffix:
                    _LOGGER.warning(
                        f"API response for group '{group_key}' contains an item with an empty string 'id'. Item: {item}. Skipping."
                    )
                    continue
            elif isinstance(api_id_value, int):
                node_id_with_suffix = str(api_id_value)
            else:
                _LOGGER.warning(
                    f"API response for group '{group_key}' contains item with missing/invalid 'id' type. Item: {item}. Skipping."
                )
                continue

            # Check for exact duplicate raw IDs within the same API response list.
            if node_id_with_suffix in raw_ids_seen_in_this_call:
                _LOGGER.error(
                    f"Exact duplicate raw node ID '{node_id_with_suffix}' in API response for group '{group_key}'. Item: {item}. Skipping."
                )
                continue
            raw_ids_seen_in_this_call.add(node_id_with_suffix)

            item_text_value = item.get("text")
            # Check for missing 'text' field.
            if item_text_value is None:
                _LOGGER.warning(
                    f"API response for group '{group_key}', node '{node_id_with_suffix}', missing 'text'. Item: {item}. Skipping."
                )
                continue

            node_id_clean = strip_hdg_node_suffix(node_id_with_suffix)

            # Prevent stale polling data from overwriting a recently set value.
            # Compare the time the node was last *set* against the start time of this polling cycle.
            last_set_time = self._last_set_times.get(node_id_clean, 0.0)
            if last_set_time > polling_start_time_monotonic:
                _LOGGER.debug(
                    f"Skipping update for node '{node_id_clean}' (from API ID '{node_id_with_suffix}') "
                    f"from polling group '{group_key}': Value was set more recently (at {last_set_time:.2f}s mono) "
                    f"than this polling cycle start ({polling_start_time_monotonic:.2f}s mono)."
                )
                continue

            # Check for duplicate *cleaned* node IDs within the same API response list.
            if node_id_clean in cleaned_node_ids_processed_this_call:
                existing_value = self.data.get(node_id_clean)
                if existing_value != item_text_value:
                    _LOGGER.critical(
                        f"Duplicate base node ID '{node_id_clean}' (from API ID '{node_id_with_suffix}') "
                        f"in API response for group '{group_key}' WITH CONFLICTING VALUES. "
                        f"Existing: '{existing_value}', New (skipped): '{item_text_value}'. Data integrity compromised."
                    )
                else:
                    _LOGGER.debug(
                        f"Duplicate base node ID '{node_id_clean}' (from API ID '{node_id_with_suffix}') "
                        f"in API response for group '{group_key}' with identical value. Skipping."
                    )
                continue

            # Store the value in the coordinator's data dictionary.
            self.data[node_id_clean] = item_text_value
            cleaned_node_ids_processed_this_call.add(node_id_clean)
            successfully_processed_and_stored_items.append(item)
        return successfully_processed_and_stored_items

    async def _fetch_group_data(
        self, group_key: str, payload_config: NodeGroupPayload, polling_start_time_monotonic: float
    ) -> Optional[List[Dict[str, Any]]]:
        """
        Fetch data for a single polling group from the HDG API.

        Acquires the API lock before making the request. Handles API-specific
        errors and connection issues.

        Args:
            group_key: The key identifying the polling group.
            payload_config: The configuration for the polling group, including the API payload string.
            polling_start_time_monotonic: The monotonic time when the current overall polling cycle started.
                                          This is passed to `_parse_and_store_api_items` to help
                                          prevent stale polled data from overwriting recently set values.

        Returns:
            A list of successfully processed data items, or None if an API response error occurred.
            Raises HdgApiConnectionError on connection issues or asyncio.TimeoutError if the API lock cannot be acquired.
        """
        payload_str = payload_config.get("payload_str")
        if payload_str is None:
            _LOGGER.error(
                f"Config error: 'payload_str' missing for group '{group_key}'. Cannot fetch."
            )
            return None

        try:
            # Acquire the API lock with a timeout to prevent blocking the polling cycle indefinitely.
            async with async_timeout.timeout(POLLING_API_LOCK_TIMEOUT_S):
                async with self._api_lock:
                    start_time_group_fetch_actual = time.monotonic()
                    if self.enable_debug_logging:
                        _LOGGER.info(
                            f"FETCHING (lock acquired) for group: {group_key} at {dt_util.as_local(dt_util.utcnow())}"
                        )
                    fetched_data_list = await self.api_client.async_get_nodes_data(payload_str)

            if fetched_data_list is not None:
                # Parse and store the fetched items if the API call was successful.
                successfully_processed_items = self._parse_and_store_api_items(
                    group_key, fetched_data_list, polling_start_time_monotonic
                )
                _LOGGER.debug(
                    f"Processed data for HDG group: {group_key}. {len(successfully_processed_items)} valid items."
                )
                if self.enable_debug_logging:
                    duration_fetch_actual = time.monotonic() - start_time_group_fetch_actual
                    _LOGGER.info(
                        f"COMPLETED FETCH for group: {group_key}. Duration (API call + parse): {duration_fetch_actual:.2f}s"
                    )
                return successfully_processed_items
            else:
                # This case should ideally not be hit if async_get_nodes_data raises on failure.
                _LOGGER.warning(
                    f"Polling for group {group_key} returned None from api_client without error."
                )
                return None

        except HdgApiConnectionError as conn_err:
            self._log_fetch_error_duration(
                group_key,
                "Connection error",
                polling_start_time_monotonic,
                conn_err,
            )
            raise
        except HdgApiResponseError as err:
            # Log API response errors but don't raise UpdateFailed immediately.
            self._log_fetch_error_duration(
                group_key, "API response error", polling_start_time_monotonic, err
            )
            return None  # Data for this group may be stale
        except asyncio.TimeoutError:  # Timeout for acquiring API lock
            _LOGGER.warning(
                f"Polling for group {group_key} timed out after {POLLING_API_LOCK_TIMEOUT_S}s "
                "waiting for API lock. Skipping fetch for this group."
            )
            return None
        except Exception as err:
            _LOGGER.exception(f"Unexpected error polling group '{group_key}': {err}")
            raise

    async def async_config_entry_first_refresh(self) -> None:
        """
        Perform the initial sequential data refresh for all polling groups.

        This method is called once during the setup of the config entry.
        It fetches data for each polling group in `POLLING_GROUP_ORDER` sequentially
        with a small delay between groups to avoid overwhelming the boiler.
        If any group fails due to a connection error, it logs the error and continues
        with other groups. If *no* data is fetched from *any* group successfully,
        it raises `UpdateFailed` to signal a critical setup failure.
        """
        start_time_first_refresh = time.monotonic()
        if self.enable_debug_logging:
            _LOGGER.info(
                f"INITIATING async_config_entry_first_refresh for {self.name} at {dt_util.as_local(dt_util.utcnow())} "
                f"with {INITIAL_SEQUENTIAL_INTER_GROUP_DELAY_S}s inter-group delay..."
            )
        any_group_failed_connection = False
        any_group_fetched_successfully_at_all = False
        initial_data_items_fetched_count = 0

        for i, group_key in enumerate(POLLING_GROUP_ORDER):
            payload_config = HDG_NODE_PAYLOADS.get(group_key)
            if not payload_config:
                _LOGGER.warning(
                    f"Skipping initial poll for group '{group_key}': not defined in HDG_NODE_PAYLOADS."
                )
                continue

            _LOGGER.debug(f"Initial sequential poll for group: {group_key}")
            current_group_fetch_start_time = time.monotonic()
            try:
                # _fetch_group_data raises HdgApiConnectionError on connection issues.
                processed_items = await self._fetch_group_data(
                    group_key, payload_config, current_group_fetch_start_time
                )
                if processed_items is not None:
                    self._last_update_times[group_key] = time.monotonic()
                    initial_data_items_fetched_count += len(processed_items)
                    any_group_fetched_successfully_at_all = True
                    _LOGGER.debug(
                        f"Initial poll for group {group_key} successful, {len(processed_items)} items processed."
                    )
                else:
                    # No explicit 'except HdgApiResponseError' here; it's handled within _fetch_group_data
                    # by returning None and logging a warning, which is acceptable for initial refresh
                    # as long as *some* groups succeed.
                    _LOGGER.warning(
                        f"Initial poll for group {group_key} reported failure (e.g., API response error)."
                    )
            except HdgApiConnectionError as err:
                _LOGGER.warning(
                    f"Initial poll for group {group_key} failed with connection error: {err}"
                )
                any_group_failed_connection = True
            except Exception as err:
                _LOGGER.exception(
                    f"Unexpected error during initial poll of group {group_key}: {err}"
                )
                any_group_failed_connection = (
                    True  # Treat unexpected as potential connection issue for reporting
                )

            if i < len(POLLING_GROUP_ORDER) - 1:
                _LOGGER.debug(
                    f"Waiting {INITIAL_SEQUENTIAL_INTER_GROUP_DELAY_S}s before polling next group."
                )
                await asyncio.sleep(INITIAL_SEQUENTIAL_INTER_GROUP_DELAY_S)

        # If no group was fetched successfully, the integration cannot function.
        if not any_group_fetched_successfully_at_all:
            _LOGGER.error(
                f"Initial data refresh for {self.name} failed to retrieve any data from any group. "
                f"Connection issues encountered: {any_group_failed_connection}. "
                "Setup will be retried by Home Assistant."
            )
            raise UpdateFailed(
                "Failed to retrieve any data from HDG boiler during initial setup. Check logs."
            )
        # Check if self.data is empty even if some groups reported success (shouldn't happen with current logic, but as a safeguard).
        elif not self.data:
            _LOGGER.warning(
                f"Initial data refresh for {self.name} completed, but no data was fetched. "
                "This is unexpected if some groups were reported as fetched. Please check logs."
            )

        end_time_first_refresh = time.monotonic()
        if self.enable_debug_logging:
            _LOGGER.info(
                f"COMPLETED async_config_entry_first_refresh for {self.name}. "
                f"Duration: {end_time_first_refresh - start_time_first_refresh:.2f}s. "
                f"Approx {initial_data_items_fetched_count} node values updated. Total items in data: {len(self.data or [])}"
            )
        self.async_set_updated_data(self.data)

    def _get_due_polling_groups(
        self, current_time_monotonic: float
    ) -> list[tuple[str, NodeGroupPayload]]:
        """
        Identify which polling groups are due for an update based on their scan intervals.

        Args:
            current_time_monotonic: The current monotonic time.

        Returns:
            A list of (group_key, payload_config) tuples for groups that need fetching.
        """
        due_groups: list[tuple[str, NodeGroupPayload]] = []
        for group_key in POLLING_GROUP_ORDER:
            payload_config = HDG_NODE_PAYLOADS.get(group_key)

            if not payload_config or group_key not in self.scan_intervals:
                _LOGGER.debug(
                    f"Skipping group '{group_key}' in due check: not defined or no scan_interval."
                )
                continue

            group_scan_interval_seconds = self.scan_intervals[group_key].total_seconds()
            last_update_time_for_group = self._last_update_times.get(group_key, 0.0)

            if (current_time_monotonic - last_update_time_for_group) >= group_scan_interval_seconds:
                due_groups.append((group_key, payload_config))
            elif self.enable_debug_logging:
                _LOGGER.debug(
                    f"Skipping poll for HDG group: {group_key} (Next in approx. {max(0, group_scan_interval_seconds - (current_time_monotonic - last_update_time_for_group)):.0f}s)"
                )
        return due_groups

    async def _sequentially_fetch_due_groups_data(
        self, due_groups: list[tuple[str, NodeGroupPayload]], polling_cycle_start_time: float
    ) -> tuple[bool, bool]:
        """
        Sequentially fetch data for a list of due polling groups with delays.

        Args:
            due_groups: List of (group_key, payload_config) tuples for groups to fetch.
            polling_cycle_start_time: Monotonic time when the current polling cycle started.
                                      Passed to _fetch_group_data for stale data checks.

        Returns:
            A tuple: (any_group_fetched_successfully, any_connection_error_encountered).
        """
        any_group_fetched_successfully = False
        any_connection_error_encountered = False

        for i, (group_key, payload_config) in enumerate(due_groups):
            _LOGGER.debug(
                f"Fetching data for due group: {group_key} (Index {i+1} of {len(due_groups)})"
            )
            try:
                # Pass the start time of the *entire* polling cycle for stale data check.
                processed_items = await self._fetch_group_data(
                    group_key, payload_config, polling_cycle_start_time
                )
                if processed_items is not None:
                    self._last_update_times[group_key] = time.monotonic()
                    any_group_fetched_successfully = True
            except HdgApiConnectionError as err:
                _LOGGER.warning(
                    f"Connection error for group {group_key} during sequential fetch: {err}. Skipping."
                )
                any_connection_error_encountered = True
            except Exception as err:  # Catch any other unexpected errors during fetch/processing.
                _LOGGER.exception(
                    f"Unexpected error processing group {group_key} in _async_update_data: {err}. Skipping."
                )

            if i < len(due_groups) - 1:
                _LOGGER.debug(
                    f"Waiting {INITIAL_SEQUENTIAL_INTER_GROUP_DELAY_S}s before polling next due group."
                )
                await asyncio.sleep(INITIAL_SEQUENTIAL_INTER_GROUP_DELAY_S)

        return any_group_fetched_successfully, any_connection_error_encountered

    async def _async_update_data(self) -> Dict[str, Any]:
        """
        Periodically called by Home Assistant's DataUpdateCoordinator to fetch data.

        This method identifies which polling groups are due for an update and
        sequentially fetches data for them. It handles connection errors by
        raising `UpdateFailed` but logs API response errors as warnings,
        allowing the coordinator to continue with potentially stale data for those groups.
        If no groups are successfully fetched and there were groups due, and connection
        errors were the cause, `UpdateFailed` is raised.

        Returns:
            The current state of `self.data` after attempting updates.
        """
        polling_cycle_start_time = time.monotonic()
        if self.enable_debug_logging:
            _LOGGER.info(
                f"INITIATING _async_update_data cycle at {dt_util.as_local(dt_util.utcnow())}"
            )

        due_groups_to_fetch = self._get_due_polling_groups(polling_cycle_start_time)

        if not due_groups_to_fetch:
            _LOGGER.debug("No polling groups were due for an update.")
            if self.enable_debug_logging:
                duration_no_tasks = time.monotonic() - polling_cycle_start_time
                _LOGGER.info(
                    f"COMPLETED _async_update_data cycle (no groups due). Duration: {duration_no_tasks:.3f}s"
                )
            return self.data

        _LOGGER.debug(f"Due groups to fetch: {[g[0] for g in due_groups_to_fetch]}")

        (
            any_group_fetched_successfully,
            any_connection_error_encountered,
        ) = await self._sequentially_fetch_due_groups_data(
            due_groups_to_fetch, polling_cycle_start_time
        )

        # If no groups were successfully fetched AND there were groups due, report failure.
        if not any_group_fetched_successfully and due_groups_to_fetch:
            msg = "Failed to fetch data from HDG boiler for all due groups."
            if any_connection_error_encountered:
                msg += " Connection errors encountered with one or more groups."
                _LOGGER.error(msg)
                raise UpdateFailed(msg)
            else:
                msg += " API errors or other issues for all attempted groups. Data may be stale."
                _LOGGER.warning(msg)

        if self.enable_debug_logging:
            duration_with_tasks = time.monotonic() - polling_cycle_start_time
            _LOGGER.info(
                f"COMPLETED _async_update_data cycle (processed {len(due_groups_to_fetch)} due groups). "
                f"Duration: {duration_with_tasks:.3f}s"
            )
        return self.data

    async def async_update_internal_node_state(self, node_id: str, new_value: str) -> None:
        """
        Update a node's value in the internal data store and notify listeners.

        This method is called after a successful API set operation via the
        `_set_value_worker`. It updates the `self.data` dictionary, records the
        time of the set operation for stale data prevention, and then calls
        `self.async_set_updated_data()` to inform listeners if the value changed.

        Args:
            node_id: The base HDG node ID (without suffix) whose state is to be updated.
            new_value: The new string value for the node.
        """
        if not isinstance(new_value, str):
            _LOGGER.warning(
                f"async_update_internal_node_state called for node '{node_id}' with non-string value '{new_value}' (type: {type(new_value)}). Converting to string."
            )
        # Only update and notify if the value has actually changed.
        if self.data.get(node_id) != new_value:
            self._last_set_times[node_id] = time.monotonic()
            self.data[node_id] = new_value
            _LOGGER.debug(
                f"Internal state for node '{node_id}' updated to '{new_value}'. Notifying listeners."
            )
            self.async_set_updated_data(self.data)
        else:
            _LOGGER.debug(
                f"Internal state for node '{node_id}' already '{new_value}'. No update needed."
            )

    async def _set_value_worker(self) -> None:
        """
        Background worker task to process pending set value requests.

        This task waits for the `_new_set_value_event` to be set, indicating
        that there are pending set requests in `_pending_set_values`. It then
        processes these requests sequentially from the `_pending_set_values` dictionary,
        making API calls and updating the internal state, while respecting the API lock
        and a cooldown period between set operations.
        """
        _LOGGER.info("HDG set_value_worker started.")
        while True:
            try:
                # Wait until there's a new value to process.
                await self._new_set_value_event.wait()
                self._new_set_value_event.clear()

                items_to_process_this_cycle: List[tuple[str, str, str]] = []
                async with self._pending_set_values_lock:
                    # Atomically get and clear the pending requests.
                    if not self._pending_set_values:
                        continue
                    items_to_process_this_cycle.extend(
                        (node_id, value_str, entity_name)
                        for node_id, (
                            value_str,
                            entity_name,
                        ) in self._pending_set_values.items()
                    )
                    self._pending_set_values.clear()

                _LOGGER.debug(
                    f"Set_value_worker: Processing {len(items_to_process_this_cycle)} items: "
                    f"{[(item[2], item[0], item[1]) for item in items_to_process_this_cycle]}"
                )

                # Process each pending item sequentially.
                for node_id, value_str, entity_name in items_to_process_this_cycle:
                    try:
                        async with self._api_lock:
                            _LOGGER.debug(
                                f"Set_value_worker: Acquired API lock for node '{entity_name}' (ID: {node_id})."
                            )
                            # Make the API call to set the value.
                            success = await self.api_client.async_set_node_value(node_id, value_str)
                            if success:
                                _LOGGER.info(
                                    f"Set_value_worker: Successfully set node '{entity_name}' (ID: {node_id}) to '{value_str}' via API."
                                )
                                await self.async_update_internal_node_state(node_id, value_str)
                            else:
                                # Log API reported failure, but don't raise to keep worker alive.
                                _LOGGER.error(
                                    f"Set_value_worker: API call to set node '{entity_name}' (ID: {node_id}) to '{value_str}' reported failure."
                                )
                            _LOGGER.debug(
                                f"Set_value_worker: Cooling down for {SET_NODE_COOLDOWN_S}s after API call for node '{entity_name}' (ID: {node_id})."
                            )
                            await asyncio.sleep(SET_NODE_COOLDOWN_S)
                    except HdgApiConnectionError as e:
                        # Log connection errors, item is not retried in this cycle.
                        _LOGGER.error(
                            f"Set_value_worker: Connection error for node '{entity_name}' (ID: {node_id}): {e}. Item not retried this cycle."
                        )
                    except Exception as e:
                        # Log unexpected errors during processing of a single item.
                        _LOGGER.exception(
                            f"Set_value_worker: Unexpected error processing item for node '{entity_name}' (ID: {node_id}): {e}"
                        )
            except asyncio.CancelledError:
                _LOGGER.info("HDG set_value_worker cancelled.")
                break
            except Exception as e:
                _LOGGER.exception(f"HDG set_value_worker main loop crashed: {e}")
                # Sleep briefly to prevent a tight loop if the crash is persistent.
                await asyncio.sleep(5)
        _LOGGER.info("HDG set_value_worker stopped.")

    async def async_set_node_value_if_changed(
        self,
        node_id: str,
        new_value_str_for_api: str,
        entity_name_for_log: str = "Unknown Entity",
    ) -> bool:
        """
        Queue a node value to be set via the API if it's different from the current known value.

        This method checks if the `new_value_str_for_api` is different from the
        current value stored in `self.data` for the given `node_id`. If it is
        different, or if the node is not currently in `self.data`, the request
        (node_id, value, entity_name) is added to the `_pending_set_values`
        dictionary (overwriting any previous pending request for the same node_id)
        and the `_new_set_value_event` is set to signal the `_set_value_worker`.

        Args:
            node_id: The base HDG node ID (without TUVWXY suffix) to set.
            new_value_str_for_api: The value to set, already formatted as a string
                                   suitable for the API.
            entity_name_for_log: A descriptive name of the entity or source making
                                 the request, used for logging.

        Returns:
            True if the request was successfully queued (or if the value was already
            the same), False if an unexpected error occurred during queueing.

        Raises:
            TypeError: If `new_value_str_for_api` is not a string.
        """
        if not isinstance(new_value_str_for_api, str):
            _LOGGER.error(
                f"Invalid type for new_value_str_for_api: {type(new_value_str_for_api).__name__} for node '{entity_name_for_log}' (ID: {node_id}). Expected str."
            )
            raise TypeError("new_value_str_for_api must be a string.")

        # Check if the value is already the same as the current known state.
        current_known_raw_value = self.data.get(node_id)

        if current_known_raw_value is not None and current_known_raw_value == new_value_str_for_api:
            _LOGGER.info(
                f"Coordinator: Value for node '{entity_name_for_log}' (ID: {node_id}) is already '{new_value_str_for_api}'. Skipping update."
            )
            return True

        try:
            # Add the request to the pending queue and signal the worker.
            async with self._pending_set_values_lock:
                self._pending_set_values[node_id] = (new_value_str_for_api, entity_name_for_log)
            self._new_set_value_event.set()
            _LOGGER.info(
                f"Updated pending set request for node '{entity_name_for_log}' (ID: {node_id}) with value '{new_value_str_for_api}'. Pending count: {len(self._pending_set_values)}"
            )
            return True
        except Exception as e:
            _LOGGER.error(
                f"Unexpected error updating pending set values for node '{entity_name_for_log}' (ID: {node_id}): {e}",
                # Include exc_info for traceback on unexpected errors.
                exc_info=True,
            )
            return False

    async def async_stop_set_value_worker(self) -> None:
        """
        Gracefully stop the background set_value_worker task.

        Cancels the task and waits for it to finish execution, with a timeout.
        """
        if self._set_value_worker_task and not self._set_value_worker_task.done():
            _LOGGER.debug("Cancelling HDG set_value_worker task...")
            self._set_value_worker_task.cancel()
            try:
                await asyncio.wait_for(self._set_value_worker_task, timeout=10.0)
                _LOGGER.debug("HDG set_value_worker task successfully cancelled and joined.")
            except asyncio.CancelledError:
                _LOGGER.debug("HDG set_value_worker task caught CancelledError during stop.")
            except asyncio.TimeoutError:
                _LOGGER.warning("Timeout waiting for HDG set_value_worker task to stop.")
            except Exception as e:
                _LOGGER.exception(f"Unexpected error during set_value_worker task shutdown: {e}")
            finally:
                self._set_value_worker_task = None
        else:
            _LOGGER.debug("HDG set_value_worker task was not running or already stopped.")
