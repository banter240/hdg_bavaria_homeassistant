"""Manage data fetching, updates, and API interactions for the HDG Bavaria Boiler integration.

This module defines the `HdgDataUpdateCoordinator` class, which is the central
to the HDG Bavaria Boiler integration. Its responsibilities include:
- Polling data from the boiler's API for various data groups with configurable update intervals.
- Processing raw API responses and storing cleaned data.
- Coordinating requests to set values on the boiler via a dedicated worker.
- Managing API interaction efficiency, including respecting rate limits and handling
  connection/response errors.
- Dynamically adjusting polling frequency and tracking the boiler's online/offline status.
"""

from __future__ import annotations

__version__ = "0.11.0"

import asyncio
import logging
import time
from datetime import timedelta
from typing import (
    Any,
)

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.util import dt as dt_util

from .classes.polling_response_processor import (
    HdgPollingResponseProcessor,
)
from .const import (
    API_REQUEST_TYPE_GET_NODES_DATA,
    API_REQUEST_TYPE_SET_NODE_VALUE,
    COORDINATOR_FALLBACK_UPDATE_INTERVAL_MINUTES,
    COORDINATOR_MAX_CONSECUTIVE_FAILURES_BEFORE_FALLBACK,
    DOMAIN,
    INITIAL_SEQUENTIAL_INTER_GROUP_DELAY_S,
    MIN_SCAN_INTERVAL,
    POST_INITIAL_REFRESH_COOLDOWN_S,
    POLLING_RETRY_INITIAL_DELAY_S,
    POLLING_RETRY_MAX_DELAY_S,
    POLLING_RETRY_BACKOFF_FACTOR,
    POLLING_RETRY_MAX_ATTEMPTS,
    LIFECYCLE_LOGGER_NAME,
    ENTITY_DETAIL_LOGGER_NAME,
    API_LOGGER_NAME,
)
from .exceptions import (
    HdgApiConnectionError,
    HdgApiError,
    HdgApiResponseError,
    HdgApiPreemptedError,
)
from .models import NodeGroupPayload
from .helpers.api_access_manager import ApiPriority, HdgApiAccessManager
from .registry import HdgEntityRegistry


_LOGGER = logging.getLogger(DOMAIN)
_LIFECYCLE_LOGGER = logging.getLogger(LIFECYCLE_LOGGER_NAME)
_ENTITY_DETAIL_LOGGER = logging.getLogger(ENTITY_DETAIL_LOGGER_NAME)
_API_LOGGER = logging.getLogger(API_LOGGER_NAME)


class HdgDataUpdateCoordinator(DataUpdateCoordinator[dict[str, Any]]):
    """Manage fetching data from the HDG boiler and coordinate updates to entities.

    This coordinator handles polling groups with varying update intervals, processes
    API responses, and manages a worker task (`HdgSetValueWorker`) to queue and
    retry 'set value' operations. It tracks the boiler's online status based on
    polling success and dynamically adjusts polling frequency in response to
    persistent API failures.
    """

    def __init__(
        self,
        hass: HomeAssistant,
        api_access_manager: HdgApiAccessManager,
        entry: ConfigEntry,
        log_level_threshold_for_connection_errors: int,
        hdg_entity_registry: HdgEntityRegistry,
    ):
        """Initialize the HdgDataUpdateCoordinator.

        Args:
            hass: The HomeAssistant instance.
            api_access_manager: An instance of HdgApiAccessManager for communication with the boiler.
            entry: The ConfigEntry associated with this coordinator instance.
            log_level_threshold_for_connection_errors: Threshold for escalating connection error log level.
            hdg_entity_registry: The HdgEntityRegistry instance providing entity and polling group definitions.

        """
        self._consecutive_poll_failures: int = 0
        self._original_update_interval: timedelta | None = None
        self._fallback_update_interval: timedelta = timedelta(
            minutes=COORDINATOR_FALLBACK_UPDATE_INTERVAL_MINUTES
        )
        self._max_consecutive_failures_before_fallback: int = (
            COORDINATOR_MAX_CONSECUTIVE_FAILURES_BEFORE_FALLBACK
        )
        self._failed_poll_group_retry_info: dict[str, dict[str, Any]] = {}
        self._boiler_considered_online: bool = True
        self._boiler_online_event = asyncio.Event()
        if self._boiler_considered_online:
            self._boiler_online_event.set()
        self.hass = hass
        self.api_access_manager = api_access_manager
        self.entry = entry
        self._log_level_threshold_for_connection_errors = (
            log_level_threshold_for_connection_errors
        )
        self._polling_group_order = hdg_entity_registry.get_polling_group_order()
        self._hdg_node_payloads = hdg_entity_registry.get_polling_group_payloads()
        self.scan_intervals: dict[str, timedelta] = {}

        self._validate_polling_config()
        self._initialize_scan_intervals()

        self._last_update_times: dict[str, float] = {}
        self._initialize_last_update_times_monotonic()

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
        self.data: dict[str, Any] = {}
        self._last_set_times: dict[str, float] = {}
        self._polling_response_processor = HdgPollingResponseProcessor(self)

        _LOGGER.debug(
            "HdgDataUpdateCoordinator for '%s' initialized. Update interval: %s.",
            self.entry.title,
            shortest_interval,
        )

    def _initialize_scan_intervals(self) -> None:
        """Initialize scan intervals for each polling group from config or defaults."""
        current_config = self.entry.options or self.entry.data
        for group_key in self._polling_group_order:
            payload_details = self._hdg_node_payloads.get(group_key)
            if not payload_details:
                _ENTITY_DETAIL_LOGGER.error(
                    "Payload details missing for group '%s'. Skipping.", group_key
                )
                continue

            config_key = f"scan_interval_{group_key}"
            default_val = payload_details["default_scan_interval"]
            raw_val = current_config.get(config_key, str(default_val))

            try:
                scan_seconds = float(raw_val)  # type: ignore[arg-type]
                if scan_seconds < MIN_SCAN_INTERVAL:
                    _LOGGER.warning(
                        "Scan interval %ss for group '%s' is below minimum %ss. Using default: %ss.",
                        scan_seconds,
                        group_key,
                        MIN_SCAN_INTERVAL,
                        default_val,
                    )
                    scan_seconds = float(default_val)
            except (ValueError, TypeError):
                _LOGGER.warning(
                    "Invalid scan interval '%s' for group '%s'. Using default: %ss.",
                    raw_val,
                    group_key,
                    default_val,
                )
                scan_seconds = float(default_val)
            self.scan_intervals[group_key] = timedelta(seconds=scan_seconds)

    def _validate_polling_config(self) -> None:
        """Validate consistency between dynamically built polling configurations."""
        polling_group_set = set(self._polling_group_order)
        payloads_key_set = set(self._hdg_node_payloads.keys())
        if polling_group_set != payloads_key_set:
            missing_in_payloads = polling_group_set - payloads_key_set
            missing_in_order = payloads_key_set - polling_group_set
            error_msg = (
                "CRITICAL DYNAMIC CONFIG MISMATCH: POLLING_GROUP_ORDER and HDG_NODE_PAYLOADS keys do not match. "
                f"Missing in Payloads: {missing_in_payloads or 'None'}. "
                f"Missing in Order: {missing_in_order or 'None'}. "
                "This indicates an issue in polling_manager.py."
            )
            _LOGGER.critical(error_msg)
            raise ValueError(error_msg)

    @property
    def last_update_times_public(self) -> dict[str, float]:
        """Return a dictionary of last successful update times for polling groups."""
        return self._last_update_times

    @property
    def boiler_is_online(self) -> bool:
        """Return True if the boiler is currently considered online.

        The online status is determined by the success of recent polling attempts
        and is managed internally by the coordinator.
        """
        return self._boiler_considered_online

    def _cleanup_failed_poll_group_retry_info(
        self, active_poll_groups: set[str]
    ) -> None:
        """Remove retry info for polling groups that are no longer active."""
        stale_groups = (
            set(self._failed_poll_group_retry_info.keys()) - active_poll_groups
        )
        for group in stale_groups:
            del self._failed_poll_group_retry_info[group]
            _LIFECYCLE_LOGGER.debug(
                "Cleaned up stale retry info for group '%s'.", group
            )

    def _initialize_last_update_times_monotonic(self) -> None:
        """Set initial 'last update time' for all polling groups to 0.0.

        This ensures that all groups are considered due for an update on the
        first polling cycle.
        """
        for group_key in self._polling_group_order:
            self._last_update_times[group_key] = 0.0

    def _log_fetch_error_duration(
        self,
        group_key: str,
        error_type: str,
        start_time: float,
        error: Exception,
        log_level: int = logging.WARNING,
    ) -> None:
        """Log error details and duration of a failed fetch attempt.

        This helper method provides a standardized way to log errors during data fetching,
        including the duration of the failed attempt and dynamic log level selection.
        """
        duration = time.monotonic() - start_time
        log_message = "%s for group: %s at %s. Duration: %.2fs. Error: %s"
        log_args = (
            error_type.upper(),
            group_key,
            dt_util.as_local(dt_util.utcnow()),
            duration,
            error,
        )
        # Use logging.log to dynamically set the level
        if log_level == logging.ERROR:
            _LOGGER.error(log_message, *log_args)
        else:  # Default to WARNING for non-ERROR logs in this context
            _LOGGER.warning(log_message, *log_args)

    async def _fetch_group_data(
        self,
        group_key: str,
        payload_config: NodeGroupPayload,
        polling_cycle_start_time_for_log: float,
        priority: ApiPriority = ApiPriority.LOW,
    ) -> list[dict[str, Any]] | None:
        """Fetch and process data for a single polling group.

        This method uses the `HdgApiAccessManager` to submit a request to the
        boiler's API, processes the response using HdgPollingResponseProcessor,
        and handles various API-related exceptions.
        """
        payload_str: str = payload_config["payload_str"]
        try:
            _API_LOGGER.debug(
                "FETCHING for group: %s at %s via API Access Manager.",
                group_key,
                dt_util.as_local(dt_util.utcnow()),
            )
            fetched_data_list = await self.api_access_manager.submit_request(
                priority=priority,
                coroutine=self.api_access_manager._api_client.async_get_nodes_data,
                request_type=API_REQUEST_TYPE_GET_NODES_DATA,
                context_key=group_key,
                node_payload_str=payload_str,
            )

            if fetched_data_list is not None:
                processed_items = (
                    self._polling_response_processor.parse_and_store_api_items(
                        group_key, fetched_data_list
                    )
                )

                _ENTITY_DETAIL_LOGGER.debug(
                    "Processed data for HDG group: %s. %s valid items.",
                    group_key,
                    len(processed_items),
                )
                return processed_items
            _API_LOGGER.debug(
                "Polling for group '%s' returned None from api_client without error.",
                group_key,
            )
            return None
        except (
            HdgApiPreemptedError
        ) as preempt_err:  # Catch the new preemption error specifically
            self._log_fetch_error_duration(
                group_key,
                "Preempted by higher priority",
                polling_cycle_start_time_for_log,
                preempt_err,
                logging.WARNING,
            )
            raise
        # Handle specific API response errors (e.g., bad status code, non-JSON response).
        except HdgApiResponseError as err:
            self._log_fetch_error_duration(
                group_key,
                "API response error",
                polling_cycle_start_time_for_log,
                err,
                logging.WARNING,
            )
            return None
        except (
            HdgApiConnectionError
        ) as conn_err:  # Catch general connection errors, including timeouts
            self._log_fetch_error_duration(  # Corrected to use this logger function
                group_key,
                "Connection error",  # Explicitly name the type for the log.
                polling_cycle_start_time_for_log,
                conn_err,
                logging.WARNING,  # Maintain warning level here
            )
            raise  # Re-raise to be handled by the sequential fetch logic
        # Handle generic API errors.
        except HdgApiError as api_err:
            self._log_fetch_error_duration(
                group_key,
                "Generic API error",
                polling_cycle_start_time_for_log,
                api_err,
                logging.WARNING,
            )
            return None
        except Exception as err:
            # Catch any other unexpected errors during polling.
            _LOGGER.exception("Unexpected error polling group '%s': %s", group_key, err)
            raise

    async def _sequentially_fetch_groups(
        self,
        groups_to_fetch: list[tuple[str, NodeGroupPayload]],
        polling_cycle_start_time: float,
        request_priority: ApiPriority = ApiPriority.LOW,
    ) -> tuple[bool, bool]:
        """Fetch data for multiple polling groups sequentially.

        This method iterates through the provided list of groups, fetching data
        for each one with a small delay between groups to avoid overwhelming the
        API. It tracks whether any group was fetched successfully and if any
        connection errors were encountered.
        """
        any_group_fetched_successfully = False
        any_connection_error_encountered = False

        for i, (group_key, payload_config) in enumerate(groups_to_fetch):
            _ENTITY_DETAIL_LOGGER.debug(
                "Fetching data for group: %s (Index %s/%s)",
                group_key,
                i + 1,
                len(groups_to_fetch),
            )
            try:
                processed_items = await self._fetch_group_data(
                    group_key,
                    payload_config,
                    polling_cycle_start_time,
                    request_priority,
                )
                if processed_items is not None:
                    self._last_update_times[group_key] = polling_cycle_start_time
                    any_group_fetched_successfully = True
            except HdgApiConnectionError:
                any_connection_error_encountered = True
            if i < len(groups_to_fetch) - 1:
                _ENTITY_DETAIL_LOGGER.debug(
                    "Waiting %ss before next group.",
                    INITIAL_SEQUENTIAL_INTER_GROUP_DELAY_S,
                )
                await asyncio.sleep(INITIAL_SEQUENTIAL_INTER_GROUP_DELAY_S)
        return any_group_fetched_successfully, any_connection_error_encountered

    def _handle_first_refresh_outcome(
        self,
        any_group_fetched_successfully: bool,
        any_connection_error_encountered: bool,
    ) -> None:
        """Process the results of the initial data refresh.

        This method updates the boiler's online status and raises `UpdateFailed`
        if the initial refresh was unsuccessful.
        """
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
                "Initial data refresh for %s completed, but no data was fetched overall.",
                self.name,
            )
        else:
            self._boiler_considered_online = True
            self._boiler_online_event.set()

    async def async_config_entry_first_refresh(self) -> None:
        """Perform initial sequential data refresh for all polling groups.

        This method is called once when the config entry is first set up. It fetches
        all defined polling groups sequentially to populate the initial data with a
        higher priority. It raises `UpdateFailed` if no data can be retrieved,
        which may cause Home Assistant to retry the setup later.
        """
        start_time_first_refresh = time.monotonic()
        _LIFECYCLE_LOGGER.info(
            "INITIATING async_config_entry_first_refresh for %s at %s.",
            self.name,
            dt_util.as_local(dt_util.utcnow()),
        )

        all_groups_to_fetch = [
            (gk, self._hdg_node_payloads[gk])
            for gk in self._polling_group_order
            if gk in self._hdg_node_payloads
        ]

        (
            any_group_fetched_successfully,
            any_connection_error_encountered,
        ) = await self._sequentially_fetch_groups(
            all_groups_to_fetch, start_time_first_refresh, ApiPriority.MEDIUM
        )

        self._handle_first_refresh_outcome(
            any_group_fetched_successfully, any_connection_error_encountered
        )

        duration = time.monotonic() - start_time_first_refresh
        _LIFECYCLE_LOGGER.info(
            "COMPLETED async_config_entry_first_refresh for %s. Duration: %.2fs. Items: %s",
            self.name,
            duration,
            len(self.data or []),
        )
        self.async_set_updated_data(self.data)
        _ENTITY_DETAIL_LOGGER.debug(
            "Initial refresh complete. Current data size: %s.", len(self.data)
        )

        await asyncio.sleep(POST_INITIAL_REFRESH_COOLDOWN_S)
        _ENTITY_DETAIL_LOGGER.debug("Post-initial-refresh cool-down finished.")

    def _get_due_polling_groups(
        self, current_time_monotonic: float
    ) -> list[tuple[str, NodeGroupPayload]]:
        """Identify polling groups that are currently due for an update.

        A group is considered due if the time elapsed since its last successful
        update exceeds its configured scan interval. This method iterates through
        all defined polling groups in their specified order to determine which ones
        need to be polled in the current cycle.
        """
        due_groups: list[tuple[str, NodeGroupPayload]] = []
        for group_key in self._polling_group_order:
            payload_config = self._hdg_node_payloads.get(group_key)
            if not payload_config or group_key not in self.scan_intervals:
                _ENTITY_DETAIL_LOGGER.debug(
                    "Skipping group '%s' in due check: not defined or no scan_interval.",
                    group_key,
                )
                continue

            interval_seconds = self.scan_intervals[group_key].total_seconds()
            last_update = self._last_update_times.get(group_key, 0.0)

            if (current_time_monotonic - last_update) >= interval_seconds:
                due_groups.append((group_key, payload_config))
            else:
                next_poll_in = max(
                    0, interval_seconds - (current_time_monotonic - last_update)
                )
                _ENTITY_DETAIL_LOGGER.debug(
                    "Skipping poll for HDG group: %s (Next in approx. %.0fs)",
                    group_key,
                    next_poll_in,
                )
        return due_groups

    def _prepare_current_poll_cycle_groups(
        self, current_time_monotonic: float
    ) -> list[tuple[str, NodeGroupPayload]]:
        """Prepare the list of polling groups to be fetched in the current cycle.

        This method combines regularly scheduled polling groups with any groups
        that failed in a previous cycle and are marked for immediate retry.

        """
        _LIFECYCLE_LOGGER.debug("Preparing groups for current poll cycle...")

        due_groups_to_fetch_regular = self._get_due_polling_groups(
            current_time_monotonic
        )
        _LIFECYCLE_LOGGER.debug(
            "Found %s regularly due groups: %s",
            len(due_groups_to_fetch_regular),
            [g[0] for g in due_groups_to_fetch_regular],
        )

        due_groups_keys_from_retry: list[str] = []
        for group_key, retry_info in list(self._failed_poll_group_retry_info.items()):
            if current_time_monotonic >= retry_info["next_retry_time"]:
                due_groups_keys_from_retry.append(group_key)
                _LIFECYCLE_LOGGER.info(
                    "Adding previously failed group '%s' to current poll cycle for retry (attempt %s).",
                    group_key,
                    retry_info["attempts"],
                )
        _LIFECYCLE_LOGGER.debug(
            "Found %s groups to retry: %s",
            len(due_groups_keys_from_retry),
            due_groups_keys_from_retry,
        )

        all_due_groups_map: dict[str, NodeGroupPayload] = {
            g[0]: g[1] for g in due_groups_to_fetch_regular
        }
        # Add retry groups to the map if they are not already included.
        for group_key_to_retry in due_groups_keys_from_retry:
            if group_key_to_retry not in all_due_groups_map:
                if payload_config := self._hdg_node_payloads.get(group_key_to_retry):
                    all_due_groups_map[group_key_to_retry] = payload_config

        return list(all_due_groups_map.items())

    def _process_failed_poll_cycle(
        self,
        any_connection_error_encountered: bool,
        groups_in_cycle: list[tuple[str, NodeGroupPayload]],
    ) -> None:
        """Handle the logic when a polling cycle fails to fetch any group successfully.

        This method increments failure counters, updates the boiler's online status,
        adjusts the update interval on persistent failures (especially connection errors),
        and raises `UpdateFailed` for critical errors that should halt further updates.
        """
        self._consecutive_poll_failures += 1
        if self._boiler_considered_online:
            _LIFECYCLE_LOGGER.warning(
                "HDG Boiler transitioning to OFFLINE state due to poll failures."
            )
        self._boiler_considered_online = False
        self._boiler_online_event.clear()

        msg = "Failed to fetch data from HDG boiler for all attempted groups in this cycle."
        current_time = time.monotonic()

        for group_key, _ in groups_in_cycle:
            retry_info = self._failed_poll_group_retry_info.get(
                group_key, {"attempts": 0, "next_retry_time": 0.0}
            )
            retry_info["attempts"] += 1

            next_delay = min(
                POLLING_RETRY_INITIAL_DELAY_S
                * (POLLING_RETRY_BACKOFF_FACTOR ** (retry_info["attempts"] - 1)),
                POLLING_RETRY_MAX_DELAY_S,
            )
            retry_info["next_retry_time"] = current_time + next_delay

            self._failed_poll_group_retry_info[group_key] = retry_info
            self._log_failed_group_retry_info(
                group_key, retry_info, any_connection_error_encountered, next_delay
            )

            if retry_info["attempts"] >= POLLING_RETRY_MAX_ATTEMPTS:
                _LIFECYCLE_LOGGER.warning(
                    "Group '%s' has reached max retry attempts (%s). It will continue to be retried at the max backoff delay until it succeeds.",
                    group_key,
                    retry_info["attempts"],
                )
                # The group is NOT popped, allowing it to be retried indefinitely at the max delay.

        if any_connection_error_encountered and (
            self._consecutive_poll_failures
            >= self._max_consecutive_failures_before_fallback
        ):
            if self._original_update_interval is None:
                self._original_update_interval = self.update_interval  # type: ignore[assignment, has-type]
            self.update_interval = self._fallback_update_interval
            _LIFECYCLE_LOGGER.warning(
                "HDG Boiler offline for %s cycles. Switching to fallback update interval: %s",
                self._consecutive_poll_failures,
                self._fallback_update_interval,
            )
            raise UpdateFailed(msg)
        else:
            _LIFECYCLE_LOGGER.warning("%s Data may be stale for some groups.", msg)

    def _log_failed_group_retry_info(
        self,
        group_key: str,
        retry_info: dict[str, Any],
        is_connection_error: bool,
        next_retry_delay: float,
    ) -> None:
        """Log information about a failed polling group, including retry details."""
        log_msg = (
            "Connection error for group '%s'. Attempt %s, next retry in %.0fs."
            if is_connection_error
            else "Non-connection API error for group '%s'. Attempt %s, next retry in %.0fs."
        )
        log_level = (
            logging.ERROR
            if is_connection_error
            and self._consecutive_poll_failures
            >= self._log_level_threshold_for_connection_errors
            else logging.WARNING
        )
        _LOGGER.log(
            log_level, log_msg, group_key, retry_info["attempts"], next_retry_delay
        )

    def _process_successful_poll_cycle_recovery(self) -> None:
        """Handle the logic when a polling cycle has at least one successful group fetch.

        This method updates the boiler's online status, resets failure counters, and restores
        the original update interval if it was previously changed to a fallback interval.
        """
        if not self._boiler_considered_online:
            _LIFECYCLE_LOGGER.info(
                "HDG Boiler transitioning to ONLINE state after successful poll."
            )
        self._boiler_considered_online = True
        self._boiler_online_event.set()

        if self._consecutive_poll_failures > 0:
            _LIFECYCLE_LOGGER.info(
                "HDG Boiler back online or partially responsive. Resetting consecutive poll failures from %s to 0.",
                self._consecutive_poll_failures,
            )
        self._consecutive_poll_failures = 0

        for group_key in self._failed_poll_group_retry_info.copy():
            if self._last_update_times.get(group_key, 0.0) > 0.0:
                _LIFECYCLE_LOGGER.debug(
                    "Clearing retry info for group '%s' after successful poll.",
                    group_key,
                )
                self._failed_poll_group_retry_info.pop(group_key)

        if (
            self._original_update_interval is not None
            and self.update_interval == self._fallback_update_interval  # type: ignore[has-type]
        ):
            self.update_interval = self._original_update_interval
            _LIFECYCLE_LOGGER.info(
                "HDG Boiler polling successful. Restoring original update interval: %s",
                self.update_interval,  # type: ignore[attr-defined]
            )

    def _handle_poll_cycle_outcome(
        self,
        any_group_fetched_in_cycle_successfully: bool,
        any_connection_error_encountered: bool,
        groups_in_cycle: list[tuple[str, NodeGroupPayload]],
    ) -> None:
        """Process the outcome of a polling cycle, updating online status and failure counters.

        This method dispatches to helper methods for more detailed processing of
        failed or successful recovery states and may raise `UpdateFailed` if
        critical errors persist.
        """
        if not any_group_fetched_in_cycle_successfully and groups_in_cycle:
            self._process_failed_poll_cycle(
                any_connection_error_encountered, groups_in_cycle
            )
        elif any_group_fetched_in_cycle_successfully:
            self._process_successful_poll_cycle_recovery()

    async def _async_update_data(self) -> dict[str, Any]:
        """Fetch data for all polling groups that are currently due for an update.

        This is the main method called by Home Assistant to refresh data. It orchestrates the polling cycle,
        determining which groups are due, fetching their data sequentially, and updating the coordinator's
        state based on the success or failure of these fetches.
        """
        polling_cycle_start_time = time.monotonic()
        _LIFECYCLE_LOGGER.debug(
            "INITIATING _async_update_data cycle at %s",
            dt_util.as_local(dt_util.utcnow()),
        )

        due_groups_to_fetch = self._prepare_current_poll_cycle_groups(
            polling_cycle_start_time
        )

        if not due_groups_to_fetch:
            _LIFECYCLE_LOGGER.debug(
                "COMPLETED _async_update_data (no groups due). Duration: %.3fs",
                time.monotonic() - polling_cycle_start_time,
            )
            return self.data

        _ENTITY_DETAIL_LOGGER.debug(
            "Due groups to fetch in this cycle: %s",
            [g[0] for g in due_groups_to_fetch],
        )

        (
            any_group_fetched_in_cycle_successfully,
            any_connection_error_encountered,
        ) = await self._sequentially_fetch_groups(
            due_groups_to_fetch, polling_cycle_start_time, ApiPriority.LOW
        )

        self._handle_poll_cycle_outcome(
            any_group_fetched_in_cycle_successfully,
            any_connection_error_encountered,
            due_groups_to_fetch,
        )

        self._cleanup_failed_poll_group_retry_info({g[0] for g in due_groups_to_fetch})

        _LIFECYCLE_LOGGER.debug(
            "COMPLETED _async_update_data (polled %s groups: %s). Duration: %.3fs",
            len(due_groups_to_fetch),
            ", ".join([g[0] for g in due_groups_to_fetch]),
            time.monotonic() - polling_cycle_start_time,
        )
        _LOGGER.debug(
            "Finished fetching hdg_boiler (Euro50) data. Polled groups: %s. Duration: %.3fs",
            ", ".join([g[0] for g in due_groups_to_fetch]),
            time.monotonic() - polling_cycle_start_time,
        )
        return self.data

    async def async_update_internal_node_state(
        self, node_id: str, new_value: str
    ) -> None:
        """Update a node's value in the internal data store and notify listeners.

        This method is typically called by the `HdgSetValueWorker` after a successful
        API 'set value' operation. It updates the local data cache and triggers an update
        for all listening entities that depend on this coordinator.
        """
        if self.data.get(node_id) != new_value:
            self._last_set_times[node_id] = time.monotonic()
            self.data[node_id] = new_value
            _LOGGER.debug(
                "Manually updated node '%s' to '%s'.",
                node_id,
                new_value,
            )
            _ENTITY_DETAIL_LOGGER.debug(
                "Internal state for node '%s' updated to '%s'. Notifying listeners.",
                node_id,
                new_value,
            )
            self.async_set_updated_data(self.data)
        else:
            _ENTITY_DETAIL_LOGGER.debug(
                "Internal state for node '%s' already '%s'. No update needed.",
                node_id,
                new_value,
            )

    async def async_set_node_value_if_changed(
        self,
        node_id: str,
        new_value_str_for_api: str,
        entity_name_for_log: str = "Unknown Entity",
    ) -> bool:
        """Queue a node value to be set on the boiler via the API.

        This method is called by entities (e.g., `HdgBoilerNumber`) or services to request a value change.
        It submits the request to the HdgApiAccessManager, which handles queuing, prioritization (HIGH),
        and retry logic, ensuring robust and responsive write operations. A check for whether the value
        has actually changed against the coordinator's current data is intentionally omitted to
        prevent race conditions with optimistic UI updates.

        Returns:
            True if the value was successfully set (after potential retries), False otherwise.

        """
        if not isinstance(new_value_str_for_api, str):
            _LOGGER.error(
                "Invalid type for new_value_str_for_api: %s for node '%s'. Expected str.",
                type(new_value_str_for_api).__name__,
                entity_name_for_log,
            )
            raise TypeError("new_value_str_for_api must be a string.")

        _ENTITY_DETAIL_LOGGER.debug(
            "Coordinator: Queuing set request for node '%s' (ID: %s) to value '%s'.",
            entity_name_for_log,
            node_id,
            new_value_str_for_api,
        )

        try:
            success = await self.api_access_manager.submit_request(
                priority=ApiPriority.HIGH,
                coroutine=self.api_access_manager._api_client.async_set_node_value,
                request_type=API_REQUEST_TYPE_SET_NODE_VALUE,
                context_key=node_id,
                node_id=node_id,
                value=new_value_str_for_api,
            )
            if success:
                await self.async_update_internal_node_state(
                    node_id, new_value_str_for_api
                )
            return bool(success)
        except HdgApiError as e:
            _LOGGER.error("Failed to set node value via API Access Manager: %s", e)
            return False

    async def async_stop_api_access_manager(self) -> None:
        """Gracefully stop the background `HdgApiAccessManager` task."""
        await self.api_access_manager.stop()


async def async_create_and_refresh_coordinator(
    hass: HomeAssistant,
    api_access_manager: HdgApiAccessManager,
    entry: ConfigEntry,
    log_level_threshold_for_connection_errors: int,
    hdg_entity_registry: HdgEntityRegistry,
) -> HdgDataUpdateCoordinator:
    """Create, initialize, and perform the first data refresh for the coordinator.

    This factory function encapsulates the creation of the `HdgDataUpdateCoordinator`,
    performs the critical initial data refresh, and starts the background worker task for setting values.
    It is the primary entry point for setting up the coordinator during integration setup.
    """
    coordinator = HdgDataUpdateCoordinator(
        hass,
        api_access_manager,
        entry,
        log_level_threshold_for_connection_errors,
        hdg_entity_registry,
    )
    api_access_manager.start(entry)
    await coordinator.async_config_entry_first_refresh()
    return coordinator
