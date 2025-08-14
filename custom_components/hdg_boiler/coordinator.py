"""Manage data fetching, updates, and API interactions for the HDG Bavaria Boiler integration."""

from __future__ import annotations

__version__ = "0.3.1"
__all__ = ["HdgDataUpdateCoordinator", "async_create_and_refresh_coordinator"]

import asyncio
import functools
import logging
import time
from datetime import datetime, timedelta
from typing import Any, TypedDict

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import CALLBACK_TYPE, HassJob, HomeAssistant
from homeassistant.helpers.event import async_call_later
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api import HdgApiClient
from .classes.polling_response_processor import HdgPollingResponseProcessor
from .const import (
    API_REQUEST_TYPE_GET_NODES_DATA,
    API_REQUEST_TYPE_SET_NODE_VALUE,
    COORDINATOR_FALLBACK_UPDATE_INTERVAL_MINUTES,
    COORDINATOR_MAX_CONSECUTIVE_FAILURES_BEFORE_FALLBACK,
    DOMAIN,
    MIN_SCAN_INTERVAL,
    POLLING_RETRY_BACKOFF_FACTOR,
    POLLING_RETRY_INITIAL_DELAY_S,
    POLLING_RETRY_MAX_ATTEMPTS,
    POLLING_RETRY_MAX_DELAY_S,
    POST_INITIAL_REFRESH_COOLDOWN_S,
)
from .exceptions import (
    HdgApiConnectionError,
    HdgApiError,
    HdgApiResponseError,
    HdgApiPreemptedError,
)
from .helpers.api_access_manager import ApiPriority, HdgApiAccessManager
from .helpers.logging_utils import (
    _LIFECYCLE_LOGGER,
    _LOGGER,
    _USER_ACTION_LOGGER,
)
from .registry import HdgEntityRegistry


class RetryInfo(TypedDict):
    """Information for tracking retries for a failed polling group."""

    attempts: int
    next_retry_time: float


class PollingState(TypedDict):
    """State related to polling and error handling."""

    consecutive_failures: int
    consecutive_connection_failures: int
    failed_group_retry_info: dict[str, RetryInfo]
    last_update_times: dict[str, float]
    boiler_is_online: bool
    boiler_online_event: asyncio.Event


class SetterState(TypedDict):
    """State related to setting values."""

    last_set_times: dict[str, float]
    pending_timers: dict[str, CALLBACK_TYPE]
    optimistic_values: dict[str, Any]
    optimistic_times: dict[str, float]
    current_generations: dict[str, int]
    locks: dict[str, asyncio.Lock]
    initial_values: dict[str, Any]


class HdgDataUpdateCoordinator(DataUpdateCoordinator[dict[str, Any]]):
    """Manage fetching data from the HDG boiler and coordinate updates."""

    update_interval: timedelta | None

    def __init__(
        self,
        hass: HomeAssistant,
        api_client: HdgApiClient,
        api_access_manager: HdgApiAccessManager,
        entry: ConfigEntry,
        log_level_threshold_for_connection_errors: int,
        error_threshold: int,
        hdg_entity_registry: HdgEntityRegistry,
    ):
        """Initialize the HdgDataUpdateCoordinator."""
        self.hass = hass
        self.api_client = api_client
        self.api_access_manager = api_access_manager
        self.entry = entry
        self.hdg_entity_registry = hdg_entity_registry
        self._log_level_threshold = log_level_threshold_for_connection_errors
        self._error_threshold = error_threshold

        self._initialize_state()
        self._validate_polling_config()
        self.scan_intervals = self._initialize_scan_intervals()
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

        self._original_update_interval = self.update_interval
        self._fallback_update_interval = timedelta(
            minutes=COORDINATOR_FALLBACK_UPDATE_INTERVAL_MINUTES
        )
        self._polling_response_processor = HdgPollingResponseProcessor(self)
        _LOGGER.debug(
            "HdgDataUpdateCoordinator initialized. Update interval: %s",
            shortest_interval,
        )

    def _initialize_state(self) -> None:
        """Initialize the state attributes for the coordinator."""
        self._polling_state: PollingState = {
            "consecutive_failures": 0,
            "consecutive_connection_failures": 0,
            "failed_group_retry_info": {},
            "last_update_times": dict.fromkeys(
                self.hdg_entity_registry.get_polling_group_order(), 0.0
            ),
            "boiler_is_online": True,
            "boiler_online_event": asyncio.Event(),
        }
        self._polling_state["boiler_online_event"].set()

        self._setter_state: SetterState = {
            "last_set_times": {},
            "pending_timers": {},
            "optimistic_values": {},
            "optimistic_times": {},
            "current_generations": {},
            "locks": {},
            "initial_values": {},
        }

    def _set_boiler_online_status(self, is_online: bool) -> None:
        """Set and log the boiler's online status."""
        if self._polling_state["boiler_is_online"] != is_online:
            _LIFECYCLE_LOGGER.info(
                "HDG Boiler transitioning to %s state.",
                "ONLINE" if is_online else "OFFLINE",
            )
            self._polling_state["boiler_is_online"] = is_online
            if is_online:
                self._polling_state["boiler_online_event"].set()
            else:
                self._polling_state["boiler_online_event"].clear()

    def _initialize_scan_intervals(self) -> dict[str, timedelta]:
        """Initialize scan intervals for each polling group."""
        scan_intervals: dict[str, timedelta] = {}
        current_config = self.entry.options or self.entry.data
        for (
            group_key,
            payload,
        ) in self.hdg_entity_registry.get_polling_group_payloads().items():
            config_key = f"scan_interval_{group_key}"
            default_val = float(payload["default_scan_interval"])
            try:
                raw_val = max(float(current_config.get(config_key)), MIN_SCAN_INTERVAL)
            except (ValueError, TypeError):
                raw_val = default_val
            scan_intervals[group_key] = timedelta(seconds=raw_val)
        return scan_intervals

    def _validate_polling_config(self) -> None:
        """Validate consistency of polling configurations."""
        if set(self.hdg_entity_registry.get_polling_group_order()) != set(
            self.hdg_entity_registry.get_polling_group_payloads().keys()
        ):
            raise ValueError("Polling group order and payload keys mismatch.")

    @property
    def last_update_times_public(self) -> dict[str, float]:
        """Return last successful update times for polling groups."""
        return self._polling_state["last_update_times"]

    @property
    def boiler_is_online(self) -> bool:
        """Return True if the boiler is considered online."""
        return self._polling_state["boiler_is_online"]

    async def _fetch_group_data(
        self, group_key: str, payload_str: str, priority: ApiPriority
    ) -> bool:
        """Fetch and process data for a single polling group."""
        try:
            fetched_data = await self.api_access_manager.submit_request(
                priority=priority,
                coroutine=self.api_client.async_get_nodes_data,
                request_type=API_REQUEST_TYPE_GET_NODES_DATA,
                context_key=group_key,
                node_payload_str=payload_str,
            )
            if fetched_data is not None:
                self._polling_response_processor.process_api_items(
                    group_key, fetched_data
                )
                return True
            return False
        except HdgApiPreemptedError as err:
            _LOGGER.debug("Fetch for group '%s' preempted: %s", group_key, err)
            raise
        except (HdgApiResponseError, HdgApiError) as err:
            _LOGGER.warning("API error fetching group '%s': %s", group_key, err)
            return False
        except HdgApiConnectionError:
            raise
        except Exception:
            _LOGGER.exception("Unexpected error polling group '%s'.", group_key)
            raise

    async def _sequentially_fetch_groups(
        self, groups: list[tuple[str, str]], priority: ApiPriority
    ) -> bool:
        """Fetch data for multiple polling groups concurrently with a limit."""
        semaphore = asyncio.Semaphore(5)  # Limit to 5 concurrent requests

        async def fetch_with_semaphore(
            group_key: str, payload_str: str
        ) -> tuple[str, bool]:
            async with semaphore:
                try:
                    success = await self._fetch_group_data(
                        group_key, payload_str, priority
                    )
                    return group_key, success
                except HdgApiConnectionError:
                    raise  # Re-raise to be caught by the gather call
                except Exception:
                    _LOGGER.exception(
                        "Unhandled exception fetching group '%s'.", group_key
                    )
                    return group_key, False

        tasks = [fetch_with_semaphore(gk, ps) for gk, ps in groups]
        try:
            results = await asyncio.gather(*tasks)
        except HdgApiConnectionError:
            raise  # Propagate the connection error to the caller

        any_success = any(r[1] for r in results)

        for group_key, success in results:
            if success:
                self._polling_state["last_update_times"][group_key] = time.monotonic()

        return any_success

    async def async_config_entry_first_refresh(self) -> None:
        """Perform initial sequential data refresh for all polling groups."""
        _LIFECYCLE_LOGGER.info("Initiating first data refresh for %s.", self.name)
        all_groups = [
            (gk, p["payload_str"])
            for gk, p in self.hdg_entity_registry.get_polling_group_payloads().items()
        ]
        try:
            any_success = await self._sequentially_fetch_groups(
                all_groups, ApiPriority.MEDIUM
            )
            if not any_success:
                raise UpdateFailed(f"Initial data refresh failed for {self.name}.")
        except HdgApiConnectionError as err:
            raise UpdateFailed(
                f"Initial data refresh failed for {self.name} due to connection error: {err}"
            ) from err

        self._set_boiler_online_status(True)
        _LIFECYCLE_LOGGER.info("First data refresh for %s complete.", self.name)
        self.async_set_updated_data(self.data)
        await asyncio.sleep(POST_INITIAL_REFRESH_COOLDOWN_S)

    def _get_groups_to_fetch(self, current_time: float) -> dict[str, str]:
        """Identify all polling groups that are due for an update or retry."""
        payloads = self.hdg_entity_registry.get_polling_group_payloads()
        due_groups = {
            key: payloads[key]["payload_str"]
            for key, interval in self.scan_intervals.items()
            if (current_time - self._polling_state["last_update_times"].get(key, 0.0))
            >= interval.total_seconds()
        }
        retry_groups = {
            key: payloads[key]["payload_str"]
            for key, info in self._polling_state["failed_group_retry_info"].items()
            if current_time >= info["next_retry_time"]
        }
        return due_groups | retry_groups

    def _get_log_level_for_failure(self) -> int:
        """Determine the appropriate log level based on consecutive failures."""
        return (
            logging.WARNING
            if self._polling_state["consecutive_failures"] >= self._log_level_threshold
            else logging.INFO
        )

    def _handle_successful_poll(self) -> None:
        """Handle the state update after a successful poll."""
        if self._polling_state["consecutive_failures"] > 0:
            _LIFECYCLE_LOGGER.info("Boiler back online. Resetting poll failures.")
        self._polling_state["consecutive_failures"] = 0
        self._polling_state["consecutive_connection_failures"] = 0
        # Clear retry info for groups that have successfully updated.
        for group_key in list(self._polling_state["failed_group_retry_info"]):
            if self._polling_state["last_update_times"].get(group_key, 0.0) > 0:
                del self._polling_state["failed_group_retry_info"][group_key]
        if self.update_interval == self._fallback_update_interval:
            self.update_interval = self._original_update_interval
            _LIFECYCLE_LOGGER.info(
                "Polling successful. Restoring original interval: %s",
                self.update_interval,
            )

    def _update_polling_status(self, success: bool, groups_in_cycle: list[str]) -> None:
        """Update polling status, manage failures, and schedule retries."""
        if success:
            self._handle_successful_poll()
            return

        self._polling_state["consecutive_failures"] += 1
        failures = self._polling_state["consecutive_failures"]
        threshold = self._log_level_threshold

        if failures == threshold:
            _LOGGER.warning(
                "Connection to host appears to be lost (failed %d consecutive times). Suppressing further group errors.",
                failures,
            )

        log_level_for_details = logging.DEBUG if failures >= threshold else logging.INFO

        for group_key in groups_in_cycle:
            info = self._polling_state["failed_group_retry_info"].get(
                group_key, {"attempts": 0, "next_retry_time": 0.0}
            )
            info["attempts"] += 1
            delay = min(
                POLLING_RETRY_INITIAL_DELAY_S
                * (POLLING_RETRY_BACKOFF_FACTOR ** (info["attempts"] - 1)),
                POLLING_RETRY_MAX_DELAY_S,
            )
            info["next_retry_time"] = time.monotonic() + delay
            self._polling_state["failed_group_retry_info"][group_key] = info

            _LOGGER.log(
                log_level_for_details,
                "Error for group '%s'. Attempt %s, next retry in %.0fs.",
                group_key,
                info["attempts"],
                delay,
            )

            if info["attempts"] >= POLLING_RETRY_MAX_ATTEMPTS:
                _LIFECYCLE_LOGGER.warning(
                    "Group '%s' reached max retry attempts.", group_key
                )

        if failures >= COORDINATOR_MAX_CONSECUTIVE_FAILURES_BEFORE_FALLBACK:
            if self.update_interval != self._fallback_update_interval:
                self.update_interval = self._fallback_update_interval
                _LIFECYCLE_LOGGER.warning(
                    "Boiler offline. Switching to fallback interval: %s",
                    self.update_interval,
                )
            raise UpdateFailed("Persistent connection errors.")

    def _handle_update_failure(
        self, failure_type: str, context: dict[str, Any] | None = None
    ) -> dict[str, Any] | None:
        """Handle all polling and connection failures centrally."""
        context = context or {}
        self._set_boiler_online_status(False)

        if failure_type == "connection":
            self._polling_state["consecutive_connection_failures"] += 1
            failures = self._polling_state["consecutive_connection_failures"]
            threshold = self._error_threshold
            err = context.get("error")

            if failures < threshold:
                _LOGGER.debug(
                    "Connection error #%d of %d occurred. Suppressing error, will retry on next cycle.",
                    failures,
                    threshold,
                )
                return self.data  # Silently fail

            _LOGGER.warning(
                "Connection error threshold of %d reached after %d failures.",
                threshold,
                failures,
            )
            self._polling_state["consecutive_connection_failures"] = 0  # Reset
            raise UpdateFailed(f"Connection to boiler failed: {err}") from err
        elif failure_type == "poll":
            self._update_polling_status(
                success=False,
                groups_in_cycle=context.get("groups_in_cycle", []),
            )

        return None

    async def _async_update_data(self) -> dict[str, Any]:
        """Fetch data for all due polling groups."""
        groups_to_fetch = self._get_groups_to_fetch(time.monotonic())
        if not groups_to_fetch:
            return self.data

        try:
            any_success = await self._sequentially_fetch_groups(
                list(groups_to_fetch.items()), ApiPriority.LOW
            )
            self._set_boiler_online_status(any_success)
            self._update_polling_status(any_success, list(groups_to_fetch.keys()))

        except HdgApiConnectionError as err:
            result = self._handle_update_failure("connection", context={"error": err})
            if result is not None:
                return result

        self._polling_state["consecutive_connection_failures"] = 0
        return self.data

    async def async_set_node_value(
        self, node_id: str, value: str, entity_name_for_log: str, debounce_delay: float
    ) -> bool:
        """Queue a node value to be set on the boiler with debouncing."""
        if not isinstance(value, str):
            raise TypeError(f"Value for {entity_name_for_log} must be a string.")

        # If this is the first request in a potential sequence, store the initial value.
        if node_id not in self._setter_state["pending_timers"]:
            self._setter_state["initial_values"][node_id] = self.data.get(node_id)

        generation = self._setter_state["current_generations"].get(node_id, 0) + 1
        self._setter_state["current_generations"][node_id] = generation
        self._setter_state["optimistic_values"][node_id] = value
        self._setter_state["optimistic_times"][node_id] = time.monotonic()

        if node_id in self._setter_state["pending_timers"]:
            self._setter_state["pending_timers"].pop(node_id)()

        job_target = functools.partial(
            self._process_debounced_set_value,
            node_id=node_id,
            entity_name_for_log=entity_name_for_log,
            scheduled_generation=generation,
        )
        self._setter_state["pending_timers"][node_id] = async_call_later(
            self.hass, debounce_delay, HassJob(job_target, cancel_on_shutdown=True)
        )
        return True

    def _should_skip_set_request(
        self, node_id: str, entity_name_for_log: str, scheduled_generation: int
    ) -> tuple[bool, str | None]:
        """Validate if a debounced set request should be skipped."""
        if scheduled_generation != self._setter_state["current_generations"].get(
            node_id
        ):
            _USER_ACTION_LOGGER.debug(
                "Skipping stale set request for %s (Gen %s is old).",
                entity_name_for_log,
                scheduled_generation,
            )
            return True, None

        self._setter_state["pending_timers"].pop(node_id, None)
        final_value = self._setter_state["optimistic_values"].get(node_id)
        initial_value = self._setter_state["initial_values"].pop(node_id, None)

        if final_value is None:
            _USER_ACTION_LOGGER.debug(
                "Skipping set request for %s as there is no final optimistic value.",
                entity_name_for_log,
            )
            return True, None

        # Compare final value to the value before the first change in the sequence.
        if final_value == initial_value:
            _USER_ACTION_LOGGER.info(
                "Skipping set request for %s. Final value '%s' matches initial value.",
                entity_name_for_log,
                final_value,
            )
            self._setter_state["optimistic_values"].pop(node_id, None)
            self._setter_state["optimistic_times"].pop(node_id, None)
            self.async_set_updated_data(self.data)
            return True, None

        return False, final_value

    async def _execute_set_request(
        self, node_id: str, value: str, entity_name_for_log: str
    ) -> None:
        """Execute the API call to set the node value."""
        try:
            success = await self.api_access_manager.submit_request(
                priority=ApiPriority.HIGH,
                coroutine=self.api_client.async_set_node_value,
                request_type=API_REQUEST_TYPE_SET_NODE_VALUE,
                context_key=node_id,
                node_id=node_id,
                value=value,
            )
            if success:
                self.data[node_id] = value
                self._setter_state["last_set_times"][node_id] = time.monotonic()
                _LOGGER.info("Successfully set %s to '%s'.", entity_name_for_log, value)
            else:
                _LOGGER.error(
                    "Failed to set %s to '%s'. API call returned False.",
                    entity_name_for_log,
                    value,
                )
        except HdgApiError as e:
            _LOGGER.error("API error setting %s: %s", entity_name_for_log, e)
        finally:
            if self.data.get(node_id) == self._setter_state["optimistic_values"].get(
                node_id
            ):
                self._setter_state["optimistic_values"].pop(node_id, None)
                self._setter_state["optimistic_times"].pop(node_id, None)
            self.async_set_updated_data(self.data)

    async def _process_debounced_set_value(
        self,
        _: datetime,
        node_id: str,
        entity_name_for_log: str,
        scheduled_generation: int,
    ) -> None:
        """Process the debounced set value and send it to the API."""
        lock = self._setter_state["locks"].setdefault(node_id, asyncio.Lock())
        async with lock:
            should_skip, final_value = self._should_skip_set_request(
                node_id, entity_name_for_log, scheduled_generation
            )
            if should_skip:
                return

            if final_value is not None:
                await self._execute_set_request(
                    node_id, final_value, entity_name_for_log
                )

    async def async_stop_api_access_manager(self) -> None:
        """Gracefully stop the background HdgApiAccessManager task."""
        await self.api_access_manager.stop()


async def async_create_and_refresh_coordinator(
    hass: HomeAssistant,
    api_client: HdgApiClient,
    api_access_manager: HdgApiAccessManager,
    entry: ConfigEntry,
    log_level_threshold_for_connection_errors: int,
    error_threshold: int,
    hdg_entity_registry: HdgEntityRegistry,
) -> HdgDataUpdateCoordinator:
    """Create, initialize, and perform the first data refresh for the coordinator."""
    coordinator = HdgDataUpdateCoordinator(
        hass,
        api_client,
        api_access_manager,
        entry,
        log_level_threshold_for_connection_errors,
        error_threshold,
        hdg_entity_registry,
    )
    await coordinator.async_config_entry_first_refresh()
    return coordinator
