"""
Worker class for handling 'set value' operations for the HDG Bavaria Boiler.

This class provides a robust mechanism for managing asynchronous 'set value'
API calls to an HDG Bavaria boiler. It features a queue for pending operations,
retry logic with exponential backoff for transient errors (especially connection
issues), and coordination with the main data update coordinator to ensure API
access is synchronized and boiler online status is respected.
"""

from __future__ import annotations

__version__ = "0.1.1"

import asyncio
import contextlib
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
    changes. It uses an API lock shared with the coordinator to prevent concurrent
    API access. It implements retry mechanisms with exponential backoff,
    differentiating between general API errors and connection errors (which are
    retried more persistently, waiting for the boiler to come back online).
    """

    def __init__(
        self,
        coordinator: HdgDataUpdateCoordinator,
        api_client: HdgApiClient,
        api_lock: asyncio.Lock,
    ) -> None:
        """Initialize the HdgSetValueWorker."""
        self._coordinator = coordinator
        self._api_client = api_client
        self._api_lock = api_lock  # Use the coordinator's API lock

        # Stores node_id -> (value_str_for_api, entity_name_for_log)
        self._pending_set_values: dict[str, tuple[str, str]] = {}
        self._pending_set_values_lock = asyncio.Lock()
        self._new_set_value_event = asyncio.Event()

        # Stores node_id -> (retry_count, next_attempt_monotonic_time)
        # This state is managed to track retries for failed operations.
        # `next_attempt_monotonic_time` is crucial for scheduling retries.
        # `retry_count` helps in implementing exponential backoff and max retry limits.
        self._retry_state: dict[str, tuple[int, float]] = {}

        _LOGGER.debug("HdgSetValueWorker initialized.")

    def _calculate_wait_timeout(self) -> float | None:
        """Calculate the wait timeout for the worker based on retry states."""
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
        return items_to_process_now

    async def _handle_successful_set_operation(
        self, node_id: str, value_str: str, entity_name: str
    ) -> None:
        """
        Handle successful API set operation.

        Updates the coordinator's internal state and clears any retry state for the node.
        """
        log_prefix = make_log_prefix(node_id, entity_name)
        _LOGGER.info(f"{log_prefix}Successfully set node to '{value_str}' via API.")
        # Update the coordinator's data store with the new value.
        await self._coordinator.async_update_internal_node_state(node_id, value_str)
        # Clear retry state for this node as the operation was successful.
        self._retry_state.pop(node_id, None)

    async def _handle_failed_set_operation(
        self, node_id: str, value_str: str, entity_name: str, api_err: Exception
    ) -> None:
        """
        Handle a failed API set operation, including retry logic.

        Increments retry count, calculates backoff, and re-queues the item if
        retries are not exhausted. Differentiates handling for connection errors
        (more persistent retries) versus other API errors.

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
                f"{log_prefix}Connection error. Will wait for boiler to be online and retry. Error: {api_err}"
            )
            # Log if connection errors persist for an extended number of attempts.
            if (
                retry_count
                > SET_VALUE_RETRY_MAX_ATTEMPTS
                * SET_VALUE_CONNECTION_ERROR_RETRY_MULTIPLIER
            ):
                _LOGGER.error(
                    f"{log_prefix}Still failing with connection error after {retry_count - 1} attempts: {api_err}. Will continue to retry when online."
                )

        if not is_connection_error and retry_count > max_retries_for_this_error:
            _LOGGER.error(
                f"{log_prefix}Failed after {retry_count - 1} retries (general error): {api_err}. Giving up."
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
            f"{log_prefix}Failed (attempt {log_retry_count_display}/{log_max_retry_display}): {api_err}. Retrying in {actual_backoff_delay:.1f}s."
        )
        self._new_set_value_event.set()  # Signal worker to re-evaluate wait time due to new retry schedule.

    async def run(self) -> None:
        """
        Main loop for the set value worker task.

        Continuously monitors the queue for new or retryable 'set value' requests.
        It waits for the boiler to be online before attempting API calls.
        Uses an event to wake up when new items are queued or when a retry is due.
        Processes items one by one, respecting API cooldowns and handling errors.
        """
        _LOGGER.info("HdgSetValueWorker task started.")
        while True:
            try:
                # If boiler is offline and items are pending, wait for it to come online.
                if not self._coordinator.boiler_is_online and self._pending_set_values:
                    _LOGGER.info(
                        "HdgSetValueWorker: Boiler is offline. Waiting for it to come back online."
                    )
                    # Accessing coordinator's event directly
                    await self._coordinator._boiler_online_event.wait()
                    _LOGGER.info(
                        "HdgSetValueWorker: Boiler is back online. Resuming processing."
                    )

                # Calculate how long to wait: until the next retry is due, or indefinitely if no retries.
                wait_timeout = self._calculate_wait_timeout()
                with contextlib.suppress(asyncio.TimeoutError):
                    await asyncio.wait_for(
                        self._new_set_value_event.wait(), timeout=wait_timeout
                    )
                # Clear the event after waiting, regardless of timeout.
                self._new_set_value_event.clear()

                items_to_process_now = await self._collect_items_to_process()
                if not items_to_process_now:
                    continue

                _LOGGER.debug(
                    f"HdgSetValueWorker: Processing {len(items_to_process_now)} items."
                )

                for node_id, (value_str, entity_name) in items_to_process_now.items():
                    log_prefix_item = make_log_prefix(node_id, entity_name)
                    try:
                        # Double-check boiler status before making the API call.
                        if not self._coordinator.boiler_is_online:
                            _LOGGER.warning(
                                f"{log_prefix_item}Boiler went offline before processing. Re-queuing."
                            )
                            async with self._pending_set_values_lock:
                                self._pending_set_values[node_id] = (
                                    value_str,
                                    entity_name,
                                )
                            # Reset next_attempt_time to 0 to process immediately when online
                            # Retain existing retry_count.
                            self._retry_state[node_id] = (
                                self._retry_state.get(node_id, (0, 0))[0],
                                0.0,
                            )
                            self._new_set_value_event.set()
                            continue

                        async with (
                            self._api_lock
                        ):  # Use the shared API lock from coordinator.
                            _LOGGER.debug(
                                f"{log_prefix_item}Acquired API lock for set operation."
                            )
                            success = await self._api_client.async_set_node_value(
                                node_id, value_str
                            )

                        if not success:
                            raise HdgApiError(
                                f"API reported failure for set_node_value on node {node_id}"
                            )

                        await self._handle_successful_set_operation(
                            node_id, value_str, entity_name
                        )
                        _LOGGER.debug(
                            f"{log_prefix_item}Cooling down for {SET_NODE_COOLDOWN_S}s."
                        )
                        await asyncio.sleep(SET_NODE_COOLDOWN_S)

                    except (
                        HdgApiConnectionError,
                        HdgApiResponseError,
                        HdgApiError,
                    ) as api_err:
                        await self._handle_failed_set_operation(
                            node_id, value_str, entity_name, api_err
                        )
                    except Exception as e:
                        _LOGGER.exception(
                            f"{log_prefix_item}Unexpected error processing item: {e}"
                        )
                        # For unexpected errors, re-queue with basic retry logic.
                        await self._handle_failed_set_operation(
                            node_id, value_str, entity_name, e
                        )
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
        Add or update a 'set value' request in the worker's queue.
        If a request for the same node_id is already pending, it's overwritten,
        effectively debouncing to the latest value. Any existing retry state for
        that node is cleared.
        """
        log_prefix = make_log_prefix(node_id, entity_name_for_log)
        async with self._pending_set_values_lock:
            # Overwrite if already pending, effectively debouncing to the latest value
            self._pending_set_values[node_id] = (
                new_value_str_for_api,
                entity_name_for_log,
            )
            # If it was in retry_state, new value effectively cancels old retry logic for this node
            self._retry_state.pop(node_id, None)

        self._new_set_value_event.set()
        _LOGGER.info(
            f"{log_prefix}Queued set request with value '{new_value_str_for_api}'. Pending count: {len(self._pending_set_values)}"
        )
