"""Manages prioritized access to the HDG Boiler API.

This module defines the `HdgApiAccessManager` class, which acts as a central
coordinator for all API requests to the HDG boiler. It ensures that requests
are processed based on their priority (HIGH, MEDIUM, LOW) and handles
concurrency control to prevent API flooding and ensure responsiveness for
critical operations.
"""

from __future__ import annotations

from __future__ import annotations

__version__ = "0.9.0"
__all__ = ["HdgApiAccessManager", "ApiPriority"]

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
    LIFECYCLE_LOGGER_NAME,
    SET_VALUE_RETRY_ATTEMPTS,
    SET_VALUE_RETRY_DELAY_S,
)

_LIFECYCLE_LOGGER = logging.getLogger(LIFECYCLE_LOGGER_NAME)
_API_LOGGER = logging.getLogger(API_LOGGER_NAME)


class ApiPriority(Enum):
    """Defines the priority levels for API requests."""

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
    is_superseded: bool = field(default=False, compare=False)
    retry_count: int = 0


class HdgApiAccessManager:
    """Manages and prioritizes API access to the HDG Boiler."""

    def __init__(
        self,
        hass: HomeAssistant,
        api_client: HdgApiClient,
    ) -> None:
        """Initialize the API access manager."""
        self.hass = hass
        self._api_client = api_client
        self._request_queue: asyncio.PriorityQueue[
            tuple[ApiPriority, int, ApiRequest]
        ] = asyncio.PriorityQueue()
        self._request_id_counter = 0
        # This lock is crucial to prevent race conditions when multiple coroutines
        # check for and create pending requests for the same context key simultaneously.
        self._submit_lock = asyncio.Lock()
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
            _LIFECYCLE_LOGGER.debug("Cancelling API worker task...")
            self._worker_task.cancel()
            with suppress(asyncio.CancelledError):
                await self._worker_task
            _LIFECYCLE_LOGGER.debug("API worker task stopped.")
        await self._drain_queue()
        self._worker_task = None

    async def _drain_queue(self) -> None:
        """Cancel all pending requests in the queue."""
        while not self._request_queue.empty():
            _, _, request = self._request_queue.get_nowait()
            if not request.future.done():
                request.future.set_exception(
                    asyncio.CancelledError("API access manager is shutting down.")
                )
            if request.context_key:
                self._pending_requests.pop(request.context_key, None)
        _LIFECYCLE_LOGGER.debug("API request queue drained.")

    def _handle_existing_request(
        self, existing_request: ApiRequest, new_request_type: str
    ) -> Future[Any]:
        """Handle logic for an existing pending request."""
        _API_LOGGER.debug(
            "Found existing pending request for context '%s' (Type: %s).",
            existing_request.context_key,
            existing_request.request_type,
        )
        # If the new request is a high-priority SET, supersede the old one.
        if new_request_type == API_REQUEST_TYPE_SET_NODE_VALUE:
            _API_LOGGER.warning(
                "Superseding pending SET request for context '%s'.",
                existing_request.context_key,
            )
            existing_request.is_superseded = True
            # Return a new future for the new request.
            future: asyncio.Future[Any] = self.hass.loop.create_future()
            return future
        # Otherwise, the caller should wait on the existing future.
        return existing_request.future

    async def _create_and_queue_request(
        self,
        priority: ApiPriority,
        coroutine: Callable[..., Awaitable[Any]],
        request_type: str,
        context_key: str | None,
        future: Future[Any],
        *args: Any,
        **kwargs: Any,
    ) -> None:
        """Create a new ApiRequest and add it to the priority queue."""
        self._request_id_counter += 1
        request = ApiRequest(
            request_id=self._request_id_counter,
            priority=priority,
            coroutine=coroutine,
            args=args,
            kwargs=kwargs,
            future=future,
            request_type=request_type,
            context_key=context_key,
        )

        if context_key:
            self._pending_requests[context_key] = request
            future.add_done_callback(
                lambda fut: self._cleanup_pending_request(
                    context_key, request.request_id
                )
            )

        await self._request_queue.put((priority, self._request_id_counter, request))

    async def submit_request(
        self,
        priority: ApiPriority,
        coroutine: Callable[..., Awaitable[Any]],
        request_type: str,
        context_key: str | None = None,
        *args: Any,
        **kwargs: Any,
    ) -> Any:
        """Submit an API request for prioritized processing."""
        async with self._submit_lock:
            if context_key and (
                existing_request := self._pending_requests.get(context_key)
            ):
                future = self._handle_existing_request(existing_request, request_type)
                # If the future is different, a new request must be queued.
                if future is not existing_request.future:
                    await self._create_and_queue_request(
                        priority,
                        coroutine,
                        request_type,
                        context_key,
                        future,
                        *args,
                        **kwargs,
                    )
            else:
                future = self.hass.loop.create_future()
                await self._create_and_queue_request(
                    priority,
                    coroutine,
                    request_type,
                    context_key,
                    future,
                    *args,
                    **kwargs,
                )
        return await future

    def _cleanup_pending_request(self, key: str, req_id: int) -> None:
        """Remove a request from the pending dict once its future is done."""
        pending_req = self._pending_requests.get(key)
        if pending_req and pending_req.request_id == req_id:
            self._pending_requests.pop(key, None)
            _API_LOGGER.debug(
                "Cleaned up pending request for context key '%s' (ID: %s)", key, req_id
            )

    async def _retry_request(self, request: ApiRequest) -> None:
        """Place a failed, retryable request back into the queue."""
        request.retry_count += 1
        _API_LOGGER.warning(
            "Retrying set value request for context '%s'. Attempt %d of %d.",
            request.context_key,
            request.retry_count,
            SET_VALUE_RETRY_ATTEMPTS,
        )
        await asyncio.sleep(SET_VALUE_RETRY_DELAY_S)
        async with self._submit_lock:
            self._request_id_counter += 1
            await self._request_queue.put(
                (request.priority, self._request_id_counter, request)
            )

    async def _handle_request_failure(
        self, request: ApiRequest, exception: Exception
    ) -> None:
        """Handle a failed API request, including retry logic."""
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
            await self._retry_request(request)
        elif not request.future.done():
            request.future.set_exception(exception)

    async def _worker_loop(self) -> None:
        """Background task that processes API requests from the queue."""
        while True:
            try:
                _, _, request = await self._request_queue.get()

                if request.is_superseded:
                    _API_LOGGER.debug(
                        "Skipping superseded request for context '%s'",
                        request.context_key,
                    )
                    self._request_queue.task_done()
                    continue

                await self._process_request(request)

            except asyncio.CancelledError:
                _LIFECYCLE_LOGGER.debug("API worker loop cancelled.")
                break
            except Exception as e:
                _LIFECYCLE_LOGGER.exception(
                    "Unexpected error in API worker loop: %s", e
                )

    async def _process_request(self, request: ApiRequest) -> None:
        """Process a single API request."""
        _API_LOGGER.debug(
            "Processing API request: Type='%s', Priority='%s', Context='%s'",
            request.request_type,
            request.priority.name,
            request.context_key,
        )
        try:
            result = await request.coroutine(*request.args, **request.kwargs)
            if not request.future.done():
                request.future.set_result(result)
        except Exception as e:
            await self._handle_request_failure(request, e)
        finally:
            self._request_queue.task_done()
