"""Manages prioritized access to the HDG Boiler API.

This module defines the `HdgApiAccessManager` class, which acts as a central
coordinator for all API requests to the HDG boiler. It ensures that requests
are processed based on their priority (HIGH, MEDIUM, LOW) and handles
concurrency control to prevent API flooding and ensure responsiveness for
critical operations.

"""

from __future__ import annotations

import asyncio
import logging
from asyncio import Future, Task
from collections.abc import Awaitable, Callable
from contextlib import suppress
from dataclasses import dataclass, field
from enum import Enum, auto
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from ..api import HdgApiClient
from ..const import (
    API_LOGGER_NAME,
    API_REQUEST_TYPE_SET_NODE_VALUE,
    DOMAIN,
    LIFECYCLE_LOGGER_NAME,
    SET_VALUE_RETRY_ATTEMPTS,
    SET_VALUE_RETRY_DELAY_S,
)

__version__ = "0.7.0"

_LOGGER = logging.getLogger(DOMAIN)
_LIFECYCLE_LOGGER = logging.getLogger(LIFECYCLE_LOGGER_NAME)
_API_LOGGER = logging.getLogger(API_LOGGER_NAME)


class ApiPriority(Enum):
    """Defines the priority levels for API requests.

    Lower enum value indicates higher priority (used for queue ordering).
    """

    HIGH = auto()
    MEDIUM = auto()
    LOW = auto()

    def __lt__(self, other: ApiPriority) -> bool:
        """Enable comparison for PriorityQueue (lower value = higher priority)."""
        if self.__class__ is other.__class__:
            return self.value < other.value
        return NotImplemented


@dataclass(slots=True)
class ApiRequest:
    """Represents a single API request to be processed by the manager."""

    request_id: int
    priority: ApiPriority
    coroutine: Callable[..., Awaitable[Any]]
    future: Future[Any]
    request_type: str
    context_key: str | None
    args: tuple[Any, ...] = field(default_factory=tuple)
    kwargs: dict[str, Any] = field(default_factory=dict)
    start_time: float = 0.0
    is_superseded: bool = field(default=False, compare=False)
    retry_count: int = 0


class HdgApiAccessManager:
    """Manages and prioritizes API access to the HDG Boiler."""

    def __init__(
        self,
        hass: HomeAssistant,
        api_client: HdgApiClient,
        polling_preemption_timeout: float = 1.0,
    ) -> None:
        """Initialize the API access manager.

        Args:
            hass: The HomeAssistant instance.
            api_client: The low-level API client for direct communication.
            polling_preemption_timeout: Max time (seconds) a LOW priority polling
                                        request is allowed to run if a higher
                                        priority request is pending.

        """
        self.hass = hass
        self._api_client = api_client
        self._polling_preemption_timeout = polling_preemption_timeout

        self._request_queue: asyncio.PriorityQueue[tuple[int, int, ApiRequest]] = (
            asyncio.PriorityQueue()
        )
        self._request_id_counter = 0

        self._api_execution_lock = asyncio.Lock()
        self._pending_requests: dict[str, ApiRequest] = {}

        self._worker_task: Task[None] | None = None

        _LIFECYCLE_LOGGER.debug("HdgApiAccessManager initialized.")

    def start(self, entry: ConfigEntry) -> None:
        """Start the background worker task."""
        if self._worker_task is None or self._worker_task.done():
            self._worker_task = entry.async_create_background_task(
                self.hass, self._worker_loop(), name="hdg_api_access_manager_worker"
            )
            _LIFECYCLE_LOGGER.debug("HdgApiAccessManager worker task started.")

    async def stop(self) -> None:
        """Stop the background worker task gracefully."""
        if self._worker_task and not self._worker_task.done():
            _LIFECYCLE_LOGGER.debug("HdgApiAccessManager: Cancelling worker task...")
            self._worker_task.cancel()
            with suppress(asyncio.CancelledError):
                await self._worker_task
            _LIFECYCLE_LOGGER.debug("HdgApiAccessManager: Worker task stopped.")

        # Drain the queue and set exceptions on all pending futures
        while not self._request_queue.empty():
            _priority_value, _request_id, request = await self._request_queue.get()
            if not request.future.done():
                request.future.set_exception(
                    asyncio.CancelledError("API access manager is shutting down.")
                )
            # Clean up from the pending requests dict as well
            if request.context_key and request.context_key in self._pending_requests:
                self._pending_requests.pop(request.context_key, None)

            self._request_queue.task_done()
        _LIFECYCLE_LOGGER.debug("HdgApiAccessManager: Request queue drained.")

        self._worker_task = None

    async def _handle_preemption_check(
        self,
        current_request: ApiRequest,
        current_request_task: Task,
    ) -> bool:
        """Check if the currently running request should be preempted.

        Returns True if preemption occurred, False otherwise.
        """
        try:
            _priority_value, _request_id, next_request = (
                self._request_queue.get_nowait()
            )
            self._request_queue.put_nowait(
                (_priority_value, _request_id, next_request)
            )  # Put it back
        except asyncio.QueueEmpty:
            next_request = None

        if (
            next_request
            and next_request.priority < current_request.priority
            and current_request.request_type == "get_nodes_data"
            and current_request.priority == ApiPriority.LOW
            and (asyncio.get_event_loop().time() - current_request.start_time)
            > self._polling_preemption_timeout
        ):
            _API_LOGGER.warning(
                "Preempting low-priority polling request (Context: %s) due to higher priority request (Type: %s, Context: %s). Re-queuing request.",
                current_request.context_key,
                next_request.request_type,
                next_request.context_key,
            )
            current_request_task.cancel()
            async with self._api_execution_lock:
                self._request_id_counter += 1
                await self._request_queue.put(
                    (
                        current_request.priority.value,
                        self._request_id_counter,
                        current_request,
                    )
                )
            return True
        return False

    async def submit_request(
        self,
        priority: ApiPriority,
        coroutine: Callable[..., Awaitable[Any]],
        request_type: str,
        context_key: str | None = None,
        *args: Any,
        **kwargs: Any,
    ) -> Any:
        """Submit an API request to the manager for prioritized processing.

        Args:
            priority: The priority of this request.
            coroutine: The async function to call (e.g., self._api_client.async_get_nodes_data).
            request_type: A descriptive string for logging.
            context_key: Optional key for context (e.g., polling group key).
            *args: Positional arguments to pass to the coroutine.
            **kwargs: Keyword arguments to pass to the coroutine.

        Returns:
            The result of the API call.

        Raises:
            Exception: Any exception raised by the underlying API call.

        """
        # The lock ensures that checking for and creating requests is atomic.
        async with self._api_execution_lock:
            # Check for an existing, pending request for the same context key.
            if context_key and (
                existing_request := self._pending_requests.get(context_key)
            ):
                _API_LOGGER.debug(
                    "Found existing pending request for context '%s' (Type: %s).",
                    context_key,
                    existing_request.request_type,
                )

                # "Last Write Wins" logic for set_node_value requests.
                if request_type == API_REQUEST_TYPE_SET_NODE_VALUE:
                    _API_LOGGER.warning(
                        "Superseding pending SET request for context '%s'. New value will be processed.",
                        context_key,
                    )
                    existing_request.is_superseded = True
                    # The new request will adopt the future of the old one.
                    future_to_use = existing_request.future
                else:
                    # For all other request types (e.g., polling), just await the existing future.
                    return await existing_request.future
            else:
                # No pending request for this context, create a new future.
                future_to_use = self.hass.loop.create_future()

            # Create and queue the new request.
            self._request_id_counter += 1
            request = ApiRequest(
                request_id=self._request_id_counter,
                priority=priority,
                coroutine=coroutine,
                args=args,
                kwargs=kwargs,
                future=future_to_use,
                request_type=request_type,
                context_key=context_key,
            )

            if context_key:
                self._pending_requests[context_key] = request

                def _cleanup_request(fut: Future, key: str, req_id: int) -> None:
                    """Remove the request from the pending dict once its future is done."""
                    # Only remove if the completed request is the one we are tracking.
                    # This prevents a new request's callback from removing an even newer one.
                    pending_req = self._pending_requests.get(key)
                    if pending_req and pending_req.request_id == req_id:
                        self._pending_requests.pop(key, None)
                        _API_LOGGER.debug(
                            "Cleaned up pending request for context key '%s' (ID: %s)",
                            key,
                            req_id,
                        )

                request.future.add_done_callback(
                    lambda fut: _cleanup_request(fut, context_key, request.request_id)
                )

            await self._request_queue.put(
                (priority.value, self._request_id_counter, request)
            )
        return await future_to_use

    async def _handle_request_failure(
        self, request: ApiRequest, exception: Exception
    ) -> None:
        """Handle a failed API request, including retry logic for set_value."""
        _API_LOGGER.error(
            "API request failed: Type='%s', Context='%s', Error: %s",
            request.request_type,
            request.context_key,
            exception,
        )

        is_retryable = (
            request.request_type == API_REQUEST_TYPE_SET_NODE_VALUE
            and request.retry_count < SET_VALUE_RETRY_ATTEMPTS
        )

        if is_retryable:
            request.retry_count += 1
            _API_LOGGER.warning(
                "Retrying set value request for context '%s'. Attempt %s of %s.",
                request.context_key,
                request.retry_count,
                SET_VALUE_RETRY_ATTEMPTS,
            )
            await asyncio.sleep(SET_VALUE_RETRY_DELAY_S)
            # Re-queue the request for another attempt.
            async with self._api_execution_lock:
                self._request_id_counter += 1
                await self._request_queue.put(
                    (
                        request.priority.value,
                        self._request_id_counter,
                        request,
                    )
                )
        elif not request.future.done():
            # If not retryable or retries exhausted, fail the future.
            request.future.set_exception(exception)

    async def _worker_loop(self) -> None:
        """Background task that processes API requests from the queue."""
        current_request: ApiRequest | None = None
        current_request_task: Task | None = None

        while True:
            try:
                if (
                    current_request
                    and current_request_task
                    and not current_request_task.done()
                ) and await self._handle_preemption_check(
                    current_request, current_request_task
                ):
                    current_request = None
                    current_request_task = None
                    continue  # Preempted, so skip to next loop iteration

                if not current_request:
                    (
                        _priority_value,
                        _request_id,
                        request,
                    ) = await self._request_queue.get()
                    current_request = request

                    # Check if this request was superseded while in the queue.
                    if current_request.is_superseded:
                        _API_LOGGER.debug(
                            "Skipping superseded request for context '%s'",
                            current_request.context_key,
                        )
                        self._request_queue.task_done()
                        current_request = None
                        continue

                    _API_LOGGER.debug(
                        "Processing API request: Type='%s', Priority='%s', Context='%s'",
                        current_request.request_type,
                        current_request.priority.name,
                        current_request.context_key,
                    )

                    async with self._api_execution_lock:
                        current_request_task = self.hass.loop.create_task(
                            current_request.coroutine(
                                *current_request.args, **current_request.kwargs
                            )
                        )
                        current_request.start_time = asyncio.get_event_loop().time()

                if current_request_task:
                    try:
                        result = await current_request_task
                        if not current_request.future.done():
                            current_request.future.set_result(result)
                    except asyncio.CancelledError:
                        # This occurs if the task was preempted by _handle_preemption_check.
                        # The request has been re-queued, and its future is still pending.
                        # We just need to log this and let the finally block clean up.
                        _API_LOGGER.debug(
                            "Request task for context '%s' was cancelled, likely due to preemption. Moving to next request.",
                            current_request.context_key,
                        )
                    except Exception as e:
                        await self._handle_request_failure(current_request, e)
                    finally:
                        self._request_queue.task_done()
                        current_request = None
                        current_request_task = None

            except asyncio.CancelledError:
                _LIFECYCLE_LOGGER.debug("HdgApiAccessManager worker loop cancelled.")
                break
            except Exception as e:
                _LIFECYCLE_LOGGER.exception(
                    "Unexpected error in HdgApiAccessManager worker loop: %s", e
                )
