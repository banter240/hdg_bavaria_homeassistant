"""
Manages asynchronous 'set value' API calls for the HDG Bavaria Boiler.

This worker class runs as a background task, processing a queue of node value
changes. It implements retry logic with exponential backoff for transient errors,
coordinates API access with the main data update coordinator via a shared lock,
and respects the boiler's online status.
"""

from __future__ import annotations

__version__ = "0.1.10"  # Adjusted logging based on debug setting

import asyncio
import logging
import time
from typing import TYPE_CHECKING

from ..const import (
    DOMAIN,
    SET_NODE_COOLDOWN_S,
    SET_VALUE_CONNECTION_ERROR_BACKOFF_MULTIPLIER,
    SET_VALUE_CONNECTION_ERROR_RETRY_MULTIPLIER,
    SET_VALUE_MAX_INDIVIDUAL_BACKOFF_S,
    SET_VALUE_RETRY_BASE_BACKOFF_S,
    SET_VALUE_RETRY_MAX_ATTEMPTS,
)
from ..exceptions import HdgApiConnectionError, HdgApiError, HdgApiResponseError
from ..helpers.logging_utils import make_log_prefix

if TYPE_CHECKING:
    from ..api import HdgApiClient
    from ..coordinator import HdgDataUpdateCoordinator


_LOGGER = logging.getLogger(DOMAIN)


class HdgSetValueWorker:
    """
    Manages the queue, execution, and retry logic for 'set value' API calls.

    This worker runs as a background task, processing a queue of node value
    changes. It uses an API lock shared with the HdgDataUpdateCoordinator to
    prevent concurrent API access. It implements retry mechanisms with
    exponential backoff, differentiating between general API errors and
    connection errors. Connection errors are retried more persistently,
    typically waiting for the boiler to come back online.
    """

    def __init__(
        self,
        coordinator: HdgDataUpdateCoordinator,
        api_client: HdgApiClient,
        api_lock: asyncio.Lock,
    ) -> None:
        """
        Initialize the HdgSetValueWorker.

        Args:
            coordinator: The data update coordinator instance.
            api_client: The API client for communicating with the HDG boiler.
            api_lock: A shared asyncio.Lock to synchronize API access with the coordinator.
        """
        self._coordinator = coordinator
        self._api_client = api_client
        self._api_lock = api_lock  # Use the coordinator's API lock

        # Stores node_id -> (value_str_for_api, entity_name_for_log)
        # This dictionary holds the set value requests that are pending processing.
        self._pending_set_values: dict[str, tuple[str, str]] = {}
        self._pending_set_values_lock = (
            asyncio.Lock()
        )  # Lock to protect access to _pending_set_values
        self._new_set_value_event = (
            asyncio.Event()
        )  # Event to signal the worker when new items are added

        # Stores node_id -> (retry_count, next_attempt_monotonic_time)
        # This state is managed to track retries for failed operations.
        # `next_attempt_monotonic_time` is crucial for scheduling retries.
        # `retry_count` helps in implementing exponential backoff and max retry limits.
        self._retry_state: dict[str, tuple[int, float]] = {}

        _LOGGER.debug("HdgSetValueWorker initialized.")

    async def _wait_for_work_or_retry(self) -> None:
        """
        Wait until a new item is queued or the next scheduled retry is due.

        This method suspends execution until either a new 'set value' request
        is added to the queue or the timeout for the next scheduled retry is reached.
        It calculates the appropriate timeout based on the earliest next attempt time
        in the retry state.
        """
        wait_timeout = self._calculate_wait_timeout()
        if self._coordinator.enable_debug_logging:
            _LOGGER.debug(
                f"HdgSetValueWorker: Calculated wait_timeout: {wait_timeout}s. Pending items: {len(self._pending_set_values)}, Retry states: {len(self._retry_state)}"
            )

        try:
            if (
                wait_timeout is None and not self._pending_set_values
            ):  # Only wait indefinitely if no new items and no retries scheduled
                if self._coordinator.enable_debug_logging:
                    _LOGGER.debug(
                        "HdgSetValueWorker: No items or retries, waiting indefinitely for new event."
                    )
                await self._new_set_value_event.wait()
            elif wait_timeout is not None:
                if self._coordinator.enable_debug_logging:
                    _LOGGER.debug(
                        f"HdgSetValueWorker: Waiting for event or timeout of {wait_timeout:.2f}s."
                    )
                await asyncio.wait_for(
                    self._new_set_value_event.wait(), timeout=wait_timeout
                )
        except TimeoutError:
            if self._coordinator.enable_debug_logging:
                _LOGGER.debug(
                    "HdgSetValueWorker: Wait timeout reached, proceeding to check for due retries."
                )

    def _calculate_wait_timeout(self) -> float | None:
        """
        Calculate the timeout for the worker's main loop.

        The timeout is determined by the earliest `next_attempt_time` among
        all items currently in the retry state. If no items are in retry state,
        returns None, indicating the worker can wait indefinitely for new items.
        Ensures a non-negative timeout.
        """
        if not self._retry_state:
            return (
                None  # No retries pending, worker can wait indefinitely for new items.
            )

        valid_retry_times = [
            next_attempt
            for _, next_attempt in self._retry_state.values()
            if isinstance(next_attempt, int | float) and next_attempt > 0
        ]
        if not valid_retry_times:
            return None  # No valid future retry times, wait indefinitely.

        earliest_retry_time = min(valid_retry_times)
        # Calculate time until the earliest retry is due.
        # max(0, ...) ensures non-negative timeout.
        return max(0, earliest_retry_time - time.monotonic())

    async def _collect_items_to_process(self) -> dict[str, tuple[str, str]]:
        """
        Collect items from the pending queue that are due for processing.

        An item is due if it's new (retry_count == 0) or its next_attempt_time
        has been reached. Items collected are removed from the main pending queue.

        Returns:
            A dictionary containing the collected items, where keys are node IDs
            and values are tuples of (value_str, entity_name). The dictionary may be empty if no items are due.
        """
        items_to_process_now: dict[str, tuple[str, str]] = {}
        current_monotonic_time = time.monotonic()

        # Iterate over a copy of items to allow modification of the original dict.
        async with self._pending_set_values_lock:
            for node_id, data_tuple in list(self._pending_set_values.items()):
                retry_count, next_attempt_time = self._retry_state.get(
                    node_id, (0, 0.0)
                )
                if retry_count == 0 or current_monotonic_time >= next_attempt_time:
                    items_to_process_now[node_id] = data_tuple
                    # Remove from main queue, it's now being processed or will be re-added on failure
                    self._pending_set_values.pop(node_id, None)
                    if self._coordinator.enable_debug_logging:
                        _LOGGER.debug(
                            f"HdgSetValueWorker: Popped item {node_id} from pending queue for processing."
                        )
                elif self._coordinator.enable_debug_logging:
                    _LOGGER.debug(
                        f"HdgSetValueWorker: Item {node_id} not yet due for retry (next attempt in {next_attempt_time - current_monotonic_time:.2f}s)."
                    )

        if items_to_process_now and self._coordinator.enable_debug_logging:
            _LOGGER.debug(
                f"HdgSetValueWorker: Collected {len(items_to_process_now)} items to process: {list(items_to_process_now.keys())}"
            )
        return items_to_process_now

    async def _handle_successful_set_operation(
        self, node_id: str, value_str: str, entity_name: str
    ) -> None:
        """
        Handle a successful API 'set value' operation.

        This method is called after the API client confirms a successful write.
        It updates the coordinator's internal data store with the new value,
        which in turn notifies listening entities. It also clears any retry
        state associated with the given node_id, as the operation was successful.

        Args:
            node_id: The ID of the node that was successfully set.
            value_str: The string value that was set.
            entity_name: The name of the entity associated with the node, for logging.
        """
        log_prefix = make_log_prefix(node_id, entity_name)
        if self._coordinator.enable_debug_logging:
            _LOGGER.debug(
                f"{log_prefix}Successfully set node to '{value_str}' via API."
            )
        # Update the coordinator's data store with the new value.
        await self._coordinator.async_update_internal_node_state(node_id, value_str)
        # Clear retry state for this node as the operation was successful.
        self._retry_state.pop(node_id, None)

    async def _ensure_boiler_online(
        self, node_id: str, value_str: str, entity_name: str
    ) -> bool:
        """
        Check if the boiler is considered online by the coordinator.

        If the boiler is offline, this method re-queues the item for later processing
        (when the boiler comes back online) and returns False. If the boiler is online,
        it returns True, allowing processing to continue.

        Args:
            node_id: The ID of the node being processed.
            value_str: The value string for the item (used for re-queuing).
            entity_name: The entity name for logging.

        Returns:
            True if the boiler is online, False if the item was re-queued due to boiler being offline.
        """
        if not self._coordinator.boiler_is_online:
            log_prefix = make_log_prefix(node_id, entity_name)
            _LOGGER.warning(
                f"{log_prefix}Boiler went offline before processing value. Re-queuing."
            )
            async with self._pending_set_values_lock:
                self._pending_set_values[node_id] = (value_str, entity_name)
            # Reset next_attempt_time to 0 to process immediately when online
            # Retain existing retry_count.
            current_retry_count = self._retry_state.get(node_id, (0, 0))[0]
            self._retry_state[node_id] = (current_retry_count, 0.0)
            self._new_set_value_event.set()  # Signal there's work to re-evaluate
            return False
        return True

    async def _check_for_newer_pending_value(
        self, node_id: str, value_str: str, entity_name: str
    ) -> bool:
        """
        Check if a newer value for the same node is already pending in the queue.

        This prevents processing an older, stale request if the user has quickly
        submitted a new value for the same node.

        Args:
            node_id: The ID of the node being processed.
            value_str: The value string of the current item.
            entity_name: The entity name for logging.
        Returns:
            True if a newer value is pending (and this item should be skipped), False otherwise.
        """
        async with self._pending_set_values_lock:
            latest_pending_data = self._pending_set_values.get(node_id)

        if latest_pending_data and latest_pending_data[0] != value_str:
            log_prefix = make_log_prefix(node_id, entity_name)
            _LOGGER.warning(
                f"{log_prefix}A newer value '{latest_pending_data[0]}' is pending. "
                f"Skipping current set operation for older value '{value_str}'."
            )
            # The newer value will be picked up in a subsequent _collect_items_to_process call.
            return True
        return False

    async def _acquire_lock_and_set_value(
        self, node_id: str, value_str: str, entity_name: str
    ) -> bool:
        """
        Acquire the API lock, check against coordinator cache, and make the API call.

        This method first acquires the shared API lock. It then checks if the value
        to be set already matches the value in the coordinator's data cache. If so,
        the API call is skipped. Otherwise, it proceeds to call the API client
        to set the node value.

        Args:
            node_id: The ID of the node to set.
            value_str: The string value to set.
            entity_name: The entity name for logging.
        Returns:
            True if the API call was made and reported success, False if the API call was
            skipped because the value already matched the cache.
        Raises:
            HdgApiError (and subtypes): If the API call itself fails.
        """
        log_prefix = make_log_prefix(node_id, entity_name)
        async with self._api_lock:  # Use the shared API lock from coordinator.
            if self._coordinator.enable_debug_logging:
                _LOGGER.debug(
                    f"{log_prefix}Acquired API lock for set operation of '{value_str}'."
                )
            current_coordinator_value = self._coordinator.data.get(node_id)
            if self._coordinator.enable_debug_logging:
                _LOGGER.debug(
                    f"{log_prefix}Coordinator cache value for node {node_id}: '{current_coordinator_value}'. Value to set: '{value_str}'."
                )
            if (
                current_coordinator_value is not None
                and str(current_coordinator_value) == value_str
            ):
                if self._coordinator.enable_debug_logging:
                    _LOGGER.debug(
                        f"{log_prefix}Value in coordinator data ('{current_coordinator_value}') already matches value to set ('{value_str}'). Skipping API set."
                    )
                return False  # Value already matches, no API call needed.
            if self._coordinator.enable_debug_logging:
                _LOGGER.debug(
                    f"{log_prefix}Calling API to set node {node_id} to '{value_str}'."
                )
            return await self._api_client.async_set_node_value(node_id, value_str)

    async def _handle_failed_set_operation(
        self, node_id: str, value_str: str, entity_name: str, api_err: Exception
    ) -> None:
        """
        Handles a failed API set operation, including retries.

        This method is invoked when an API call to set a node value fails.
        It increments the retry count, calculates an exponential backoff delay,
        and re-queues the item for a later attempt, unless the maximum number
        of retries has been exceeded. It differentiates handling for connection errors,
        which are retried more persistently (effectively indefinitely as long as the
        boiler is offline), versus other API errors which have a fixed maximum retry count.
        The item is re-queued in `_pending_set_values` and its `_retry_state` is updated.

        Args:
            node_id: The ID of the node that failed to be set.
            value_str: The value string that was attempted.
            entity_name: The entity name for logging.
            api_err: The exception that occurred during the API call.
        """
        log_prefix = make_log_prefix(node_id, entity_name)
        retry_count, _ = self._retry_state.get(node_id, (0, 0.0))
        retry_count += 1

        is_connection_error = isinstance(api_err, HdgApiConnectionError)
        # Connection errors get effectively infinite retries while boiler is offline,
        # but still log if a high number of attempts are made.
        max_retries_for_this_error = (
            float("inf") if is_connection_error else SET_VALUE_RETRY_MAX_ATTEMPTS
        )
        base_backoff_for_this_error = (
            SET_VALUE_RETRY_BASE_BACKOFF_S
            * SET_VALUE_CONNECTION_ERROR_BACKOFF_MULTIPLIER
            if is_connection_error
            else SET_VALUE_RETRY_BASE_BACKOFF_S
        )

        if is_connection_error:
            _LOGGER.warning(
                f"{log_prefix}Connection error during set operation. Will wait for boiler to be online and retry. Error: {api_err}"
            )
            # Log if connection errors persist for an extended number of attempts.
            if (
                retry_count
                > SET_VALUE_RETRY_MAX_ATTEMPTS
                * SET_VALUE_CONNECTION_ERROR_RETRY_MULTIPLIER  # Use retry multiplier for connection errors
            ):
                _LOGGER.error(
                    f"{log_prefix}Still failing with connection error after {retry_count - 1} attempts: {api_err}. Will continue to retry when online."
                )

        if not is_connection_error and retry_count > max_retries_for_this_error:
            _LOGGER.error(
                f"{log_prefix}Failed to set value after {retry_count - 1} retries (general error): {api_err}. Giving up on this item."
            )
            self._retry_state.pop(node_id, None)  # Give up on this item.
            return  # Explicitly return after giving up.

        # If not giving up, calculate exponential backoff and re-queue.
        # Cap retry_count for backoff calculation to prevent excessively long delays.
        backoff_delay = base_backoff_for_this_error * (2 ** (min(retry_count, 10) - 1))
        actual_backoff_delay = min(backoff_delay, SET_VALUE_MAX_INDIVIDUAL_BACKOFF_S)
        next_attempt_time = time.monotonic() + actual_backoff_delay

        self._retry_state[node_id] = (retry_count, next_attempt_time)
        async with self._pending_set_values_lock:  # Re-add to pending queue for retry
            self._pending_set_values[node_id] = (value_str, entity_name)
            if self._coordinator.enable_debug_logging:
                _LOGGER.debug(
                    f"{log_prefix}Re-queued item {node_id} for retry. Next attempt in {actual_backoff_delay:.1f}s."
                )

        # Provide clear logging for retry attempts.
        log_retry_count_display = (
            f"{retry_count} (conn_err)" if is_connection_error else str(retry_count)
        )
        log_max_retry_display = (
            "inf (conn_err)"
            if max_retries_for_this_error == float("inf")
            else str(int(max_retries_for_this_error))
        )

        _LOGGER.warning(
            f"{log_prefix}Failed to set value (attempt {log_retry_count_display}/{log_max_retry_display}): {api_err}. Retrying in {actual_backoff_delay:.1f}s."
        )
        self._new_set_value_event.set()  # Signal worker to re-evaluate wait time due to new retry schedule.

    async def _process_single_item(
        self, node_id: str, value_str: str, entity_name: str
    ) -> None:
        """
        Process a single 'set value' item.

        This method orchestrates the processing of an individual item:
        1. Ensures the boiler is online.
        2. Checks if a newer value for the same node has been queued.
        3. Acquires the API lock and attempts to set the value via the API client.
        4. Handles success or failure of the API call, including retry logic.

        Args:
            node_id: The ID of the node to process.
            value_str: The value string for the item.
            entity_name: The entity name for logging.
        """
        # value_str and entity_name are passed from the items_to_process_now dictionary
        log_prefix_item = make_log_prefix(node_id, entity_name)
        if self._coordinator.enable_debug_logging:
            _LOGGER.debug(
                f"{log_prefix_item}Attempting to process set value '{value_str}'."
            )

        # Pass value_str to _ensure_boiler_online for potential re-queuing
        if not await self._ensure_boiler_online(node_id, value_str, entity_name):
            return  # Item re-queued, wait for boiler online.

        if await self._check_for_newer_pending_value(node_id, value_str, entity_name):
            return  # Newer value pending, skip this one.

        try:
            api_set_successful = await self._acquire_lock_and_set_value(
                node_id, value_str, entity_name
            )

            if api_set_successful:
                await self._handle_successful_set_operation(
                    node_id, value_str, entity_name
                )
                if self._coordinator.enable_debug_logging:
                    _LOGGER.debug(
                        f"{log_prefix_item}Set operation for '{value_str}' successful. Cooling down for {SET_NODE_COOLDOWN_S}s."
                    )
                await asyncio.sleep(SET_NODE_COOLDOWN_S)

        except (
            Exception
        ) as api_err:  # Catch any exception from _acquire_lock_and_set_value
            await self._handle_failed_set_operation(
                node_id, value_str, entity_name, api_err
            )

    async def _process_collected_items(
        self, items_to_process: dict[str, tuple[str, str]]
    ) -> None:
        """
        Iterate through and process a batch of collected items.

        For each item in the provided dictionary, this method attempts to process it
        using `_process_single_item`. It includes an item-level try-except block
        to ensure that an error in processing one item does not prevent other items
        in the batch from being attempted.

        Args:
            items_to_process: A dictionary of items to process in this batch.
        """
        if not items_to_process:
            if self._coordinator.enable_debug_logging:
                _LOGGER.debug(
                    "HdgSetValueWorker: _process_collected_items: No items to process."
                )
            return
        if self._coordinator.enable_debug_logging:
            _LOGGER.debug(
                f"HdgSetValueWorker: _process_collected_items: Processing {len(items_to_process)} items: {list(items_to_process.keys())}"
            )
        for node_id, (value_str, entity_name) in items_to_process.items():
            log_prefix_item = make_log_prefix(node_id, entity_name)
            try:
                await self._process_single_item(node_id, value_str, entity_name)
            except (
                HdgApiConnectionError,
                HdgApiResponseError,
                HdgApiError,
            ) as api_err:
                # These are expected to be handled by _handle_failed_set_operation within _process_single_item
                # This block is a safeguard or for logging if _process_single_item re-raises them unexpectedly.
                _LOGGER.error(
                    f"{log_prefix_item}_process_collected_items: API error processing item '{value_str}': {api_err}. "
                    "This should have been handled in _process_single_item."
                )
                # Ensure retry logic is triggered if not already by _process_single_item
                await self._handle_failed_set_operation(
                    node_id, value_str, entity_name, api_err
                )
            except Exception as e:
                _LOGGER.exception(
                    f"{log_prefix_item}_process_collected_items: Unexpected error processing item '{value_str}': {e}"
                )
                # For unexpected errors, re-queue with basic retry logic.
                await self._handle_failed_set_operation(
                    node_id, value_str, entity_name, e
                )

    async def run(self) -> None:
        """
        Main run loop for the set value worker task.

        This loop continuously executes processing cycles. Each cycle involves
        waiting for the boiler to be online (if necessary), waiting for new tasks
        or for retry timers to elapse, collecting due tasks, and processing them.
        It includes top-level error handling to keep the worker task alive.
        """
        _LOGGER.info("HdgSetValueWorker task started.")
        while True:
            try:
                # Wait for boiler to be online if there's pending work or retries.
                if not self._coordinator.boiler_is_online and (
                    self._pending_set_values or self._retry_state
                ):
                    _LOGGER.warning(
                        "HdgSetValueWorker: Boiler is offline. Waiting for it to come back online before processing set values."
                    )
                    # Accessing coordinator's event directly (type ignore needed as it's a protected member)
                    await self._coordinator._boiler_online_event.wait()  # type: ignore[attr-defined]
                    _LOGGER.warning(
                        "HdgSetValueWorker: Boiler is back online. Resuming processing set values."
                    )

                await self._wait_for_work_or_retry()
                self._new_set_value_event.clear()
                if self._coordinator.enable_debug_logging:
                    _LOGGER.debug("HdgSetValueWorker: Event cleared.")
                items_to_process_now = await self._collect_items_to_process()
                if items_to_process_now:  # Only call if there are items
                    await self._process_collected_items(items_to_process_now)

            except asyncio.CancelledError:
                _LOGGER.info("HdgSetValueWorker task cancelled.")
                break
            except Exception as e:
                _LOGGER.exception(f"HdgSetValueWorker main loop crashed: {e}")
                await asyncio.sleep(5)  # Prevent rapid crash loop.
        _LOGGER.info("HdgSetValueWorker task stopped.")

    async def async_queue_set_value(
        self, node_id: str, new_value_str_for_api: str, entity_name_for_log: str
    ) -> None:
        """
        Queue a 'set value' request for asynchronous processing.

        If a request for the same `node_id` is already in the pending queue
        (`_pending_set_values`), this new request will overwrite the previous one,
        effectively debouncing to the latest value. If the node was in a retry state,
        its `next_attempt_time` is reset to 0.0 to prioritize processing of the
        new value, while retaining its existing retry count (if any).
        The `_new_set_value_event` is set to signal the worker loop that new work
        is available or an existing item has been updated.

        Args:
            node_id: The ID of the node to set.
            new_value_str_for_api: The new value formatted as a string for the API.
            entity_name_for_log: The name of the entity requesting the change, for logging.
        """
        log_prefix = make_log_prefix(node_id, entity_name_for_log)
        async with self._pending_set_values_lock:
            # Overwrite if already pending, effectively debouncing to the latest value
            self._pending_set_values[node_id] = (
                new_value_str_for_api,
                entity_name_for_log,
            )
            # If it was in retry_state, new value effectively cancels old retry logic for this node.
            # Reset its next_attempt_time to 0 to ensure it's picked up quickly.
            if node_id in self._retry_state:
                current_retry_count = self._retry_state[node_id][0]
                self._retry_state[node_id] = (
                    current_retry_count,
                    0.0,  # Reset next_attempt_time to prioritize it
                )  # Keep retry count, but make it due now
                if self._coordinator.enable_debug_logging:
                    _LOGGER.debug(
                        f"{log_prefix}Updated pending set request for already retrying node. Value: '{new_value_str_for_api}'. Will process ASAP."
                    )
            else:
                # For new items or items not in retry, ensure they are processed soon by setting retry_state with next_attempt_time = 0
                self._retry_state[node_id] = (0, 0.0)

        self._new_set_value_event.set()  # Signal the worker that there's a new/updated item
        if self._coordinator.enable_debug_logging:
            _LOGGER.debug(
                f"{log_prefix}Queued set request with value '{new_value_str_for_api}'. Pending count: {len(self._pending_set_values)}. Event set."
            )
