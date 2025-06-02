"""
Manages data fetching, updates, and API interactions for the HDG Bavaria Boiler integration.

This module defines the `HdgDataUpdateCoordinator` class, which is central
to the HDG Bavaria Boiler integration. It handles polling data from the
boiler's API, managing different data groups with varying update intervals,
processing the received data, and coordinating requests to set values on the boiler.
The coordinator ensures that API interactions are managed efficiently, respecting
API rate limits, and handling potential connection or response issues. It also
manages the online/offline state of the boiler based on polling success.
"""

from __future__ import annotations

__version__ = "0.10.32"

import asyncio
import logging
import time
from asyncio import Task
from collections.abc import Mapping
from contextlib import suppress
from datetime import timedelta
from typing import (
    Any,
)

import async_timeout
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.util import dt as dt_util

from .api import HdgApiClient
from .classes.polling_response_processor import (
    HdgPollingResponseProcessor,
)
from .classes.set_value_worker import HdgSetValueWorker
from .const import (
    CONF_ENABLE_DEBUG_LOGGING,
    COORDINATOR_FALLBACK_UPDATE_INTERVAL_MINUTES,
    COORDINATOR_MAX_CONSECUTIVE_FAILURES_BEFORE_FALLBACK,
    DEFAULT_ENABLE_DEBUG_LOGGING,
    DOMAIN,
    INITIAL_SEQUENTIAL_INTER_GROUP_DELAY_S,
    MIN_SCAN_INTERVAL,
    POLLING_API_LOCK_TIMEOUT_S,
)
from .exceptions import (
    HdgApiConnectionError,
    HdgApiError,
    HdgApiResponseError,
)
from .models import NodeGroupPayload
from .polling_manager import (  # Import dynamically built structures
    HDG_NODE_PAYLOADS,
    POLLING_GROUP_ORDER,
)

_LOGGER = logging.getLogger(DOMAIN)


class HdgDataUpdateCoordinator(DataUpdateCoordinator[dict[str, Any]]):
    """
    Manages fetching data from the HDG boiler and coordinates updates to entities.

    This coordinator handles different polling groups with varying update intervals,
    processes API responses, manages an API lock to prevent concurrent requests,
    and uses a worker task to queue and retry 'set value' operations. It also
    tracks the boiler's online status based on polling success.
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
            hass: The HomeAssistant instance.
            api_client: An instance of HdgApiClient for communication with the boiler.
            entry: The ConfigEntry associated with this coordinator instance.

        Raises:
            ValueError: If there's a critical mismatch between POLLING_GROUP_ORDER and HDG_NODE_PAYLOADS.
        """
        # --- Start: Attributes for dynamic polling interval and boiler status ---
        self._consecutive_poll_failures: int = 0
        self._original_update_interval: timedelta | None = None
        self._fallback_update_interval: timedelta = timedelta(
            minutes=COORDINATOR_FALLBACK_UPDATE_INTERVAL_MINUTES
        )
        self._max_consecutive_failures_before_fallback: int = (
            COORDINATOR_MAX_CONSECUTIVE_FAILURES_BEFORE_FALLBACK
        )
        self._failed_poll_groups_to_retry: set[str] = set()
        self._boiler_considered_online: bool = True
        self._boiler_online_event = asyncio.Event()
        # Set the event if the boiler is initially considered online.
        if self._boiler_considered_online:
            self._boiler_online_event.set()
        # --- End: Attributes ---

        self.hass = hass
        self.api_client = api_client
        self.entry = entry
        current_config = self.entry.options or self.entry.data
        self.scan_intervals: dict[str, timedelta] = {}

        # Validate consistency between POLLING_GROUP_ORDER (from polling_manager)
        # and HDG_NODE_PAYLOADS (from polling_manager).
        # The ultimate source of truth for static group properties is POLLING_GROUP_DEFINITIONS in const.py,
        # which polling_manager.py uses to build HDG_NODE_PAYLOADS.
        polling_group_set = set(POLLING_GROUP_ORDER)
        payloads_key_set = set(HDG_NODE_PAYLOADS.keys())
        if polling_group_set != payloads_key_set:
            missing_in_payloads = polling_group_set - payloads_key_set
            missing_in_order = payloads_key_set - polling_group_set
            error_msg = (
                "CRITICAL DYNAMIC CONFIG MISMATCH: Dynamically built POLLING_GROUP_ORDER and HDG_NODE_PAYLOADS keys do not match. "
                f"Missing in HDG_NODE_PAYLOADS: {missing_in_payloads or 'None'}. "
                f"Missing in POLLING_GROUP_ORDER: {missing_in_order or 'None'}. "
                "This indicates an issue in polling_manager.py or its inputs."
            )
            _LOGGER.error(error_msg)
            raise ValueError(error_msg)  # Critical error, stop initialization.

        # Initialize scan intervals for each polling group from config or defaults.
        # The HDG_NODE_PAYLOADS (built by polling_manager) now contains the
        # config_key_scan_interval and default_scan_interval.
        for group_key in POLLING_GROUP_ORDER:  # Iterate in defined order
            payload_details = HDG_NODE_PAYLOADS.get(group_key)
            if not payload_details:  # Should not happen due to validation above
                _LOGGER.error(
                    f"Payload details missing for group '{group_key}' after validation. Skipping scan interval setup."
                )
                continue

            config_key_for_scan = payload_details["config_key_scan_interval"]
            default_scan_val = payload_details["default_scan_interval"]
            raw_scan_val = current_config.get(
                config_key_for_scan, str(default_scan_val)
            )
            try:
                scan_val_seconds_float = float(raw_scan_val)  # type: ignore[arg-type]
                if scan_val_seconds_float < MIN_SCAN_INTERVAL:
                    _LOGGER.warning(
                        f"Scan interval {scan_val_seconds_float}s for group '{group_key}' is below minimum {MIN_SCAN_INTERVAL}s. "
                        f"Using default: {default_scan_val}s."
                    )
                    scan_val_seconds_float = float(default_scan_val)
            except (ValueError, TypeError):
                _LOGGER.warning(
                    f"Invalid scan interval '{raw_scan_val}' for group '{group_key}'. Using default: {default_scan_val}s."
                )
                scan_val_seconds_float = float(default_scan_val)
            self.scan_intervals[group_key] = timedelta(seconds=scan_val_seconds_float)

        # Stores the monotonic time of the last successful update for each group.
        self._last_update_times: dict[str, float] = {}
        self._initialize_last_update_times_monotonic()

        # Determine the shortest scan interval to use as the base update interval for the coordinator.
        shortest_interval = (
            min(self.scan_intervals.values())
            if self.scan_intervals
            else timedelta(seconds=60)
        )

        super().__init__(
            hass,
            _LOGGER,
            name=f"{DOMAIN} ({self.entry.title})",
            update_interval=shortest_interval,
        )
        # Main data store for node values.
        self.data: dict[str, Any] = {}
        # Lock to ensure sequential API access between polling and set operations.
        self._api_lock = asyncio.Lock()
        # Tracks when a node was last set via API, used by HdgPollingResponseProcessor.
        self._last_set_times: dict[
            str, float
        ] = {}  # Still needed by HdgPollingResponseProcessor
        self._polling_response_processor = HdgPollingResponseProcessor(self)
        self._set_value_worker_instance = HdgSetValueWorker(
            self, api_client, self._api_lock
        )
        # Task handle for the background set value worker.
        self._set_value_worker_task: Task[None] | None = None

        _LOGGER.debug(
            f"HdgDataUpdateCoordinator for '{self.entry.title}' initialized. Update interval: {shortest_interval}."
        )

    @property
    def enable_debug_logging(self) -> bool:
        """Return True if detailed debug logging for polling cycles is enabled."""
        current_options: Mapping[str, Any] = self.entry.options or {}
        debug_setting = current_options.get(
            CONF_ENABLE_DEBUG_LOGGING, DEFAULT_ENABLE_DEBUG_LOGGING
        )
        return bool(debug_setting)

    @property
    def last_update_times_public(self) -> dict[str, float]:
        """Return the dictionary of last update times for polling groups."""
        return self._last_update_times

    @property
    def boiler_is_online(self) -> bool:
        """Return True if the boiler is considered online by the coordinator."""
        return self._boiler_considered_online

    def _initialize_last_update_times_monotonic(self) -> None:
        """
        Set initial 'last update time' for all polling groups to 0.0.

        This ensures that all groups are considered due for an update on the
        first polling cycle.
        """
        for group_key in POLLING_GROUP_ORDER:
            if group_key in self.scan_intervals:
                self._last_update_times[group_key] = 0.0
            else:
                _LOGGER.warning(
                    f"Polling group '{group_key}' from POLLING_GROUP_ORDER not in scan_intervals. Skipping init."
                )

    def _log_fetch_error_duration(
        self, group_key: str, error_type: str, start_time: float, error: Exception
    ) -> None:
        """
        Log error details and duration of a failed fetch attempt.

        Args:
            group_key: The key of the polling group that failed.
            error_type: A string describing the type of error (e.g., "Connection error").
            start_time: The monotonic time when the fetch attempt started.
            error: The exception that occurred.
        """
        if self.enable_debug_logging:
            duration = time.monotonic() - start_time
            _LOGGER.warning(
                f"{error_type.upper()} for group: {group_key} at {dt_util.as_local(dt_util.utcnow())}. "
                f"Duration: {duration:.2f}s. Error: {error}"
            )

    async def _fetch_group_data(
        self,
        group_key: str,
        payload_config: NodeGroupPayload,
        polling_cycle_start_time_for_log: float,
    ) -> list[dict[str, Any]] | None:
        """
        Fetch and process data for a single polling group.

        Acquires the API lock, makes the API call, processes the response,
        and handles various exceptions.

        Args:
            group_key: The key of the polling group to fetch.
            payload_config: The configuration for the polling group.
            polling_cycle_start_time_for_log: The start time of the overall polling cycle, for logging.

        Returns:
            A list of processed items if successful, None otherwise.

        Raises:
            HdgApiConnectionError: If a connection error occurs during the API call.
        """
        # 'payload_str' is a required key in NodeGroupPayload
        payload_str: str = payload_config["payload_str"]
        try:
            # Attempt to acquire the API lock with a timeout.
            async with async_timeout.timeout(POLLING_API_LOCK_TIMEOUT_S):
                async with self._api_lock:
                    start_time_group_fetch_actual = time.monotonic()
                    if self.enable_debug_logging:
                        _LOGGER.info(
                            f"FETCHING (lock acquired) for group: {group_key} at {dt_util.as_local(dt_util.utcnow())}"
                        )
                    fetched_data_list = await self.api_client.async_get_nodes_data(
                        payload_str
                    )

            # Process the fetched data if the API call was successful.
            if fetched_data_list is not None:
                processed_items = (
                    self._polling_response_processor.parse_and_store_api_items(
                        group_key, fetched_data_list
                    )
                )

                _LOGGER.debug(
                    f"Processed data for HDG group: {group_key}. {len(processed_items)} valid items."
                )
                if self.enable_debug_logging:
                    duration_fetch_actual = (
                        time.monotonic() - start_time_group_fetch_actual
                    )
                    _LOGGER.info(
                        f"COMPLETED FETCH for group: {group_key}. Duration: {duration_fetch_actual:.2f}s"
                    )
                return processed_items
            _LOGGER.warning(
                # This case indicates the API client returned None without raising an exception.
                f"Polling for group {group_key} returned None from api_client without error."
            )
            return None
        except HdgApiConnectionError as conn_err:
            self._log_fetch_error_duration(
                group_key,
                "Connection error",
                polling_cycle_start_time_for_log,
                conn_err,
            )
            raise
        # Handle specific API response errors (e.g., bad status code, non-JSON response).
        except HdgApiResponseError as err:
            self._log_fetch_error_duration(
                group_key, "API response error", polling_cycle_start_time_for_log, err
            )
            return None
        except TimeoutError:
            _LOGGER.warning(
                f"Polling for group {group_key} timed out after {POLLING_API_LOCK_TIMEOUT_S}s waiting for API lock."
            )
            return None
        # Handle generic API errors.
        except HdgApiError as api_err:
            self._log_fetch_error_duration(
                group_key,
                "Generic API error",
                polling_cycle_start_time_for_log,
                api_err,
            )
            return None
        except Exception as err:
            # Catch any other unexpected errors during polling.
            _LOGGER.exception(f"Unexpected error polling group '{group_key}': {err}")
            raise

    async def _sequentially_fetch_groups(
        self,
        groups_to_fetch: list[tuple[str, NodeGroupPayload]],
        polling_cycle_start_time: float,
    ) -> tuple[bool, bool]:
        """
        Fetch data for multiple polling groups sequentially.

        Iterates through the provided list of groups, fetching data for each one
        with a delay between groups. Tracks overall success and connection errors.

        Args:
            groups_to_fetch: A list of tuples, each containing a group key and its payload config.
            polling_cycle_start_time: The start time of the overall polling cycle.

        Returns:
            A tuple: (any_group_fetched_successfully, any_connection_error_encountered).
        """
        any_group_fetched_successfully = False
        any_connection_error_encountered = False

        for i, (group_key, payload_config) in enumerate(groups_to_fetch):
            _LOGGER.debug(
                f"Fetching data for group: {group_key} (Index {i + 1}/{len(groups_to_fetch)})"
            )
            try:
                processed_items = await self._fetch_group_data(
                    group_key, payload_config, polling_cycle_start_time
                )
                if processed_items is not None:
                    self._last_update_times[group_key] = time.monotonic()
                    # Mark success if at least one item was processed for this group.
                    any_group_fetched_successfully = True
            except HdgApiConnectionError as err:
                _LOGGER.warning(
                    f"Connection error for group {group_key} during sequential fetch: {err}."
                )
                self._failed_poll_groups_to_retry.add(group_key)
                any_connection_error_encountered = True
            # Introduce a delay between fetching groups to avoid overwhelming the API.
            if i < len(groups_to_fetch) - 1:
                _LOGGER.debug(
                    f"Waiting {INITIAL_SEQUENTIAL_INTER_GROUP_DELAY_S}s before next group."
                )
                await asyncio.sleep(INITIAL_SEQUENTIAL_INTER_GROUP_DELAY_S)
        return any_group_fetched_successfully, any_connection_error_encountered

    async def async_config_entry_first_refresh(self) -> None:
        """
        Perform initial sequential data refresh for all polling groups.

        This is called once when the config entry is first set up. It fetches
        all defined polling groups sequentially to populate the initial data.
        Raises `UpdateFailed` if no data can be retrieved, which may cause
        Home Assistant to retry the setup.
        """
        start_time_first_refresh = time.monotonic()
        if self.enable_debug_logging:
            _LOGGER.info(
                f"INITIATING async_config_entry_first_refresh for {self.name} at {dt_util.as_local(dt_util.utcnow())} "
                f"with {INITIAL_SEQUENTIAL_INTER_GROUP_DELAY_S}s inter-group delay."
            )

        # Prepare a list of all defined polling groups.
        all_groups_to_fetch = [
            (gk, HDG_NODE_PAYLOADS[gk])
            for gk in POLLING_GROUP_ORDER
            if gk in HDG_NODE_PAYLOADS
        ]

        (
            any_group_fetched_successfully,
            any_connection_error_encountered,
        ) = await self._sequentially_fetch_groups(
            all_groups_to_fetch, start_time_first_refresh
        )

        # Handle the outcome of the initial refresh.
        if not any_group_fetched_successfully:
            error_message = (
                f"Initial data refresh for {self.name} failed to retrieve any data."
            )
            if any_connection_error_encountered:
                error_message += " Connection errors encountered."
                self._boiler_considered_online = False
                self._boiler_online_event.clear()
            else:
                error_message += (
                    " No connection errors, but all groups failed to yield data."
                )
            _LOGGER.error(error_message)
            raise UpdateFailed(error_message)
        elif not self.data:
            _LOGGER.warning(
                f"Initial data refresh for {self.name} completed, but no data was fetched overall."
            )
        else:
            self._boiler_considered_online = True
            self._boiler_online_event.set()

        if self.enable_debug_logging:
            duration = time.monotonic() - start_time_first_refresh
            _LOGGER.info(
                f"COMPLETED async_config_entry_first_refresh for {self.name}. Duration: {duration:.2f}s. "
                f"Items: {len(self.data or [])}"
            )
        self.async_set_updated_data(self.data)

    def _get_due_polling_groups(
        self, current_time_monotonic: float
    ) -> list[tuple[str, NodeGroupPayload]]:
        """
        Identify polling groups that are due for an update based on their scan intervals.

        Args:
            current_time_monotonic: The current monotonic time.

        Returns:
            A list of tuples, each containing the group key and payload configuration
            for groups that are due for an update.
        """
        due_groups: list[tuple[str, NodeGroupPayload]] = []
        for group_key in POLLING_GROUP_ORDER:
            payload_config = HDG_NODE_PAYLOADS.get(group_key)
            if not payload_config or group_key not in self.scan_intervals:
                _LOGGER.debug(
                    f"Skipping group '{group_key}' in due check: not defined or no scan_interval."
                )
                continue

            # Calculate if the group is due based on its scan interval and last update time.
            interval_seconds = self.scan_intervals[group_key].total_seconds()
            last_update = self._last_update_times.get(group_key, 0.0)

            # If the time since the last update exceeds the interval, the group is due.
            if (current_time_monotonic - last_update) >= interval_seconds:
                due_groups.append((group_key, payload_config))
            elif self.enable_debug_logging:
                next_poll_in = max(
                    0, interval_seconds - (current_time_monotonic - last_update)
                )
                _LOGGER.debug(
                    f"Skipping poll for HDG group: {group_key} (Next in approx. {next_poll_in:.0f}s)"
                )
        return due_groups

    def _prepare_current_poll_cycle_groups(
        self, current_time_monotonic: float
    ) -> list[tuple[str, NodeGroupPayload]]:
        """
        Prepare the list of polling groups to be fetched in the current cycle.

        This includes regularly scheduled groups and any groups marked for retry
        from previous failed attempts.
        """
        # Get regularly scheduled groups.
        if self.enable_debug_logging:
            _LOGGER.debug("Preparing groups for current poll cycle...")

        due_groups_to_fetch_regular = self._get_due_polling_groups(
            current_time_monotonic
        )

        # Get groups marked for retry from previous failed attempts.
        due_groups_keys_from_retry = list(self._failed_poll_groups_to_retry)
        self._failed_poll_groups_to_retry.clear()

        all_due_groups_map: dict[str, NodeGroupPayload] = {
            g[0]: g[1] for g in due_groups_to_fetch_regular
        }
        # Add retry groups to the map if they are not already included.
        for group_key_to_retry in due_groups_keys_from_retry:
            if group_key_to_retry not in all_due_groups_map:
                if payload_config := HDG_NODE_PAYLOADS.get(group_key_to_retry):
                    all_due_groups_map[group_key_to_retry] = payload_config
                    _LOGGER.info(
                        f"Adding previously failed group '{group_key_to_retry}' to current poll cycle for retry."
                    )

        return list(all_due_groups_map.items())

    def _process_failed_poll_cycle(
        self,
        any_connection_error_encountered: bool,
        groups_in_cycle: list[tuple[str, NodeGroupPayload]],
    ) -> None:
        """
        Handle the logic when a polling cycle fails to fetch any group successfully.

        Increments failure counters, updates boiler online status, adjusts update
        intervals on persistent failures, and raises `UpdateFailed` for critical errors.

        Args:
            any_connection_error_encountered: True if any connection error occurred during the cycle.
            groups_in_cycle: The list of groups that were attempted in this cycle.
        """
        self._consecutive_poll_failures += 1
        if self._boiler_considered_online:
            _LOGGER.warning(
                "HDG Boiler transitioning to OFFLINE state due to poll failures."
            )
        self._boiler_considered_online = False
        self._boiler_online_event.clear()

        msg = "Failed to fetch data from HDG boiler for all attempted groups in this cycle."
        # Handle connection errors more strictly.
        if any_connection_error_encountered:
            msg += " Connection errors were encountered."
            _LOGGER.error(msg)
            if (
                self._consecutive_poll_failures
                >= self._max_consecutive_failures_before_fallback
                and self.update_interval != self._fallback_update_interval  # type: ignore[has-type]
            ):
                if self._original_update_interval is None:
                    # Store the original interval before switching to fallback.
                    self._original_update_interval = self.update_interval  # type: ignore[assignment, has-type]
                self.update_interval = self._fallback_update_interval
                _LOGGER.warning(
                    f"HDG Boiler offline for {self._consecutive_poll_failures} cycles. "
                    f"Switching to fallback update interval: {self._fallback_update_interval}"
                )
            raise UpdateFailed(msg)  # Connection errors are critical.
        else:
            # No connection errors, but all groups failed (e.g., API response errors).
            # Mark these groups for retry in the next cycle.
            _LOGGER.warning(
                f"{msg} Other API errors or no data returned. Data may be stale."
            )
            for group_key, _ in groups_in_cycle:
                self._failed_poll_groups_to_retry.add(group_key)

    def _process_successful_poll_cycle_recovery(self) -> None:
        """
        Handle the logic when a polling cycle has at least one successful group fetch.

        Updates boiler online status, resets failure counters, and restores
        the original update interval if it was previously changed to fallback.
        """
        if not self._boiler_considered_online:
            _LOGGER.info(
                "HDG Boiler transitioning to ONLINE state after successful poll."
            )
        self._boiler_considered_online = True
        self._boiler_online_event.set()

        if self._consecutive_poll_failures > 0:
            _LOGGER.info(
                f"HDG Boiler back online or partially responsive. "
                f"Resetting consecutive poll failures from {self._consecutive_poll_failures} to 0."
            )
        self._consecutive_poll_failures = 0

        # If previously switched to fallback interval, restore the original one.
        if (
            self._original_update_interval is not None
            and self.update_interval == self._fallback_update_interval  # type: ignore[has-type]
        ):
            self.update_interval = self._original_update_interval
            _LOGGER.info(
                "HDG Boiler polling successful. Restoring original update interval: "
                f"{self.update_interval}"  # type: ignore[attr-defined]
            )
            self._original_update_interval = None

    def _handle_poll_cycle_outcome(
        self,
        any_group_fetched_in_cycle_successfully: bool,
        any_connection_error_encountered: bool,
        groups_in_cycle: list[tuple[str, NodeGroupPayload]],
    ) -> None:
        """Handle the outcome of a polling cycle, updating state and raising errors if needed.
        Dispatches to specific handlers for failed or successful cycles."""
        if not any_group_fetched_in_cycle_successfully and groups_in_cycle:
            self._process_failed_poll_cycle(
                any_connection_error_encountered, groups_in_cycle
            )
        elif (
            not self._boiler_considered_online
            and any_group_fetched_in_cycle_successfully
        ):
            _LOGGER.info(
                "HDG Boiler transitioning to ONLINE state after successful poll."
            )
        if any_group_fetched_in_cycle_successfully:
            self._boiler_considered_online = True
            self._boiler_online_event.set()
            self._process_successful_poll_cycle_recovery()

    async def _async_update_data(self) -> dict[str, Any]:
        """
        Fetch data for all polling groups that are currently due for an update.

        This is the main method called by Home Assistant to refresh data.
        It determines due groups, fetches them sequentially, and handles outcomes.
        """
        # Record start time for logging cycle duration.
        polling_cycle_start_time = time.monotonic()
        if self.enable_debug_logging:
            _LOGGER.info(
                f"INITIATING _async_update_data cycle at {dt_util.as_local(dt_util.utcnow())}"
            )

        due_groups_to_fetch = self._prepare_current_poll_cycle_groups(
            polling_cycle_start_time
        )

        # If no groups are due, return current data.
        if not due_groups_to_fetch:
            if self.enable_debug_logging:
                _LOGGER.info(
                    f"COMPLETED _async_update_data (no groups due). Duration: {time.monotonic() - polling_cycle_start_time:.3f}s"
                )
            return self.data

        _LOGGER.debug(
            f"Due groups to fetch in this cycle: {[g[0] for g in due_groups_to_fetch]}"
        )

        # Fetch data for due groups.
        (
            any_group_fetched_in_cycle_successfully,
            any_connection_error_encountered,
        ) = await self._sequentially_fetch_groups(
            due_groups_to_fetch, polling_cycle_start_time
        )

        # Process the outcome of the polling cycle.
        self._handle_poll_cycle_outcome(
            any_group_fetched_in_cycle_successfully,
            any_connection_error_encountered,
            due_groups_to_fetch,
        )

        if self.enable_debug_logging:
            _LOGGER.info(
                f"COMPLETED _async_update_data (processed {len(due_groups_to_fetch)} groups). Duration: {time.monotonic() - polling_cycle_start_time:.3f}s"
            )
        return self.data

    async def async_update_internal_node_state(
        self, node_id: str, new_value: str
    ) -> None:
        """
        Update a node's value in the internal data store and notify listeners.

        This is typically called by the `HdgSetValueWorker` after a successful API set operation.

        Args:
            node_id: The ID of the node to update.
            new_value: The new string value for the node.
        """
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

    async def async_set_node_value_if_changed(
        self,
        node_id: str,
        new_value_str_for_api: str,
        entity_name_for_log: str = "Unknown Entity",
    ) -> bool:
        """
        Queue a node value to be set on the boiler via the API.

        This method is called by entities (e.g., `HdgBoilerNumber`) or services
        to request a value change. It delegates the actual API call to the
        `HdgSetValueWorker`.

        Args:
            node_id: The ID of the node to set.
            new_value_str_for_api: The new value formatted as a string for the API.
            entity_name_for_log: The name of the entity requesting the change, for logging.

        Returns:
            True if the value was successfully queued, False otherwise.

        Raises:
            TypeError: If `new_value_str_for_api` is not a string.
        """
        if not isinstance(new_value_str_for_api, str):
            _LOGGER.error(
                f"Invalid type for new_value_str_for_api: {type(new_value_str_for_api).__name__} for node '{entity_name_for_log}'. Expected str."
            )
            raise TypeError("new_value_str_for_api must be a string.")

        # Check if the value is already set to avoid redundant API calls.
        current_known_raw_value = self.data.get(node_id)
        if (
            current_known_raw_value is not None
            and current_known_raw_value == new_value_str_for_api
        ):
            _LOGGER.info(
                f"Coordinator: Value for node '{entity_name_for_log}' (ID: {node_id}) is already '{new_value_str_for_api}'. Skipping API set."
            )
            return True

        # Queue the set value request with the worker.
        try:
            await self._set_value_worker_instance.async_queue_set_value(
                node_id, new_value_str_for_api, entity_name_for_log
            )
            return True
        except TypeError as e:
            _LOGGER.error(f"TypeError calling worker's async_queue_set_value: {e}")
            return False
        except Exception as e:
            _LOGGER.exception(
                f"Unexpected error updating pending set values for node '{entity_name_for_log}' (ID: {node_id}): {e}"
            )
            return False

    async def async_stop_set_value_worker(self) -> None:
        """
        Gracefully stop the background `_set_value_worker` task.

        This is called during integration unload to ensure clean shutdown.
        """
        if self._set_value_worker_task and not self._set_value_worker_task.done():
            _LOGGER.debug("Cancelling HDG set_value_worker task...")
            self._set_value_worker_task.cancel()
            with suppress(asyncio.TimeoutError, asyncio.CancelledError):
                await asyncio.wait_for(self._set_value_worker_task, timeout=10.0)
                _LOGGER.debug(
                    "HDG set_value_worker task successfully joined after cancellation."
                )
            self._set_value_worker_task = None
        else:
            _LOGGER.debug(
                "HDG set_value_worker task was not running or already stopped."
            )
