"""Manage data fetching, updates, and API interactions for the HDG Bavaria Boiler integration."""

from __future__ import annotations

__version__ = "0.3.16"
__all__ = ["HdgDataUpdateCoordinator", "async_create_and_refresh_coordinator"]

import asyncio
from dataclasses import dataclass, field
import functools
import logging
import time
from datetime import datetime, timedelta
from typing import Any, TypedDict
from urllib.parse import urlparse

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import CALLBACK_TYPE, HassJob, HomeAssistant
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.event import (
    async_call_later,
    async_track_time_interval,
)
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.util import dt as dt_util

from .api import HdgApiClient
from .classes.polling_response_processor import HdgPollingResponseProcessor
from .const import (
    API_REQUEST_TYPE_GET_NODES_DATA,
    API_REQUEST_TYPE_SET_NODE_VALUE,
    CONF_FALLBACK_PING_INTERVAL,
    CONF_LOG_LEVEL_THRESHOLD_FOR_PREEMPTION_ERRORS,
    COORDINATOR_FALLBACK_UPDATE_INTERVAL_MINUTES,
    COORDINATOR_MAX_CONSECUTIVE_FAILURES_BEFORE_FALLBACK,
    DEFAULT_FALLBACK_PING_INTERVAL,
    DEFAULT_LOG_LEVEL_THRESHOLD_FOR_PREEMPTION_ERRORS,
    DOMAIN,
    MAX_FALLBACK_PING_INTERVAL,
    MIN_FALLBACK_PING_INTERVAL,
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
from .helpers.network_utils import async_execute_icmp_ping
from .helpers.string_utils import strip_hdg_node_suffix
from .registry import HdgEntityRegistry


class RetryInfo(TypedDict):
    """Information for tracking retries for a failed polling group."""

    attempts: int
    next_retry_time: float


@dataclass(slots=True)
class PollingState:
    """State related to polling and error handling."""

    consecutive_failures: int = 0
    consecutive_connection_failures: int = 0
    consecutive_preemption_failures: int = 0
    failed_group_retry_info: dict[str, RetryInfo] = field(default_factory=dict)
    last_update_times: dict[str, float] = field(default_factory=dict)
    last_update_success_time: datetime | None = None
    boiler_is_online: bool = True
    boiler_online_event: asyncio.Event = field(default_factory=asyncio.Event)

    @classmethod
    def create_initial(cls, group_keys: list[str]) -> PollingState:
        """Create a new PollingState instance with initialized dictionaries."""
        state = cls()
        state.last_update_times = dict.fromkeys(group_keys, 0.0)
        state.boiler_online_event.set()
        return state


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
        self._setup_initial_active_nodes()
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

        self._hostname = urlparse(self.api_client.base_url).hostname
        self._ping_unsub: CALLBACK_TYPE | None = None

        _LOGGER.debug(
            "HdgDataUpdateCoordinator initialized. Update interval: %s",
            shortest_interval,
        )

    def _initialize_state(self) -> None:
        """Initialize the state attributes for the coordinator."""
        self._polling_state = PollingState.create_initial(
            self.hdg_entity_registry.get_polling_group_order()
        )

        self._setter_state: SetterState = {
            "last_set_times": {},
            "pending_timers": {},
            "optimistic_values": {},
            "optimistic_times": {},
            "current_generations": {},
            "locks": {},
            "initial_values": {},
        }
        self._active_node_ids: set[str] = set()

    def _setup_initial_active_nodes(self) -> None:
        """Populate initial active node IDs from the entity registry or defaults."""
        ent_reg = er.async_get(self.hass)
        entries = er.async_entries_for_config_entry(ent_reg, self.entry.entry_id)

        if not entries:
            self._active_node_ids = (
                self.hdg_entity_registry.get_default_active_node_ids()
            )
            _LOGGER.debug(
                "First-time setup: Pre-populated %d default active nodes.",
                len(self._active_node_ids),
            )
            return

        for entry in entries:
            if not entry.disabled:
                if (
                    node_id
                    := self.hdg_entity_registry.resolve_node_id_from_entity_entry(entry)
                ):
                    self._active_node_ids.add(node_id)

        _LOGGER.debug(
            "Pre-populated %d active nodes from Entity Registry.",
            len(self._active_node_ids),
        )

    def register_node(self, node_id: str) -> None:
        """Register a node ID as active (canonicalized)."""
        canonical = strip_hdg_node_suffix(node_id)
        self._active_node_ids.add(canonical)
        _LOGGER.debug(
            "Registered node '%s' (canonical: '%s'). Total active: %d",
            node_id,
            canonical,
            len(self._active_node_ids),
        )

    def unregister_node(self, node_id: str) -> None:
        """Unregister a node ID."""
        canonical = strip_hdg_node_suffix(node_id)
        self._active_node_ids.discard(canonical)
        _LOGGER.debug(
            "Unregistered node '%s' (canonical: '%s'). Total active: %d",
            node_id,
            canonical,
            len(self._active_node_ids),
        )

    def _set_boiler_online_status(self, is_online: bool) -> None:
        """Set and log the boiler's online status."""
        if self._polling_state.boiler_is_online != is_online:
            _LIFECYCLE_LOGGER.info(
                "HDG Boiler transitioning to %s state.",
                "ONLINE" if is_online else "OFFLINE",
            )
            self._polling_state.boiler_is_online = is_online
            if is_online:
                self._polling_state.boiler_online_event.set()
            else:
                self._polling_state.boiler_online_event.clear()

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
        return self._polling_state.last_update_times

    @property
    def boiler_is_online(self) -> bool:
        """Return True if the boiler is considered online."""
        return self._polling_state.boiler_is_online

    def get_diagnostics_state(self) -> dict[str, Any]:
        """Return a dictionary of internal state for diagnostics."""
        now_monotonic = time.monotonic()
        now_utc = dt_util.utcnow()

        def _monotonic_to_utc_iso(monotonic_time: float) -> str | None:
            if monotonic_time <= 0:
                return None
            dt = now_utc - timedelta(seconds=(now_monotonic - monotonic_time))
            iso_str: str = dt.isoformat()
            return iso_str

        return {
            "last_update_time_successful": (
                self._polling_state.last_update_success_time.isoformat()
                if self._polling_state.last_update_success_time
                else None
            ),
            "consecutive_poll_failures": self._polling_state.consecutive_failures,
            "boiler_considered_online": self._polling_state.boiler_is_online,
            "last_update_times_per_group_monotonic": self._polling_state.last_update_times.copy(),
            "last_update_times_per_group_utc": {
                k: _monotonic_to_utc_iso(v)
                for k, v in self._polling_state.last_update_times.items()
            },
            "failed_poll_group_retry_info": {
                k: {
                    "attempts": v["attempts"],
                    "next_retry_monotonic": v["next_retry_time"],
                    "next_retry_utc": _monotonic_to_utc_iso(v["next_retry_time"]),
                }
                for k, v in self._polling_state.failed_group_retry_info.items()
                if v["next_retry_time"] > 0
            },
        }

    async def _fetch_group_data(self, group_key: str, priority: ApiPriority) -> bool:
        """Fetch and process data for a single polling group."""
        optimized_payload, active_count, total_count = (
            self.hdg_entity_registry.get_optimized_payload_for_group(
                group_key, self._active_node_ids
            )
        )

        if optimized_payload is None:
            _LOGGER.debug("Skipping poll for group '%s': no active nodes.", group_key)
            return True

        payload_str = optimized_payload

        _LOGGER.debug(
            "Payload for group '%s': %d/%d nodes active.",
            group_key,
            active_count,
            total_count,
        )

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
                self._polling_state.consecutive_preemption_failures = 0
                return True
            return False
        except HdgApiPreemptedError as err:
            self._polling_state.consecutive_preemption_failures += 1
            threshold = self.entry.options.get(
                CONF_LOG_LEVEL_THRESHOLD_FOR_PREEMPTION_ERRORS,
                DEFAULT_LOG_LEVEL_THRESHOLD_FOR_PREEMPTION_ERRORS,
            )
            if self._polling_state.consecutive_preemption_failures >= threshold:
                _LOGGER.warning("Fetch for group '%s' preempted: %s", group_key, err)
            else:
                _LOGGER.info("Fetch for group '%s' preempted: %s", group_key, err)
            return False
        except HdgApiConnectionError:
            raise
        except (HdgApiResponseError, HdgApiError) as err:
            _LOGGER.warning("API error fetching group '%s': %s", group_key, err)
            return False
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
                    success = await self._fetch_group_data(group_key, priority)
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
                self._polling_state.last_update_times[group_key] = time.monotonic()

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
            self._set_boiler_online_status(
                False
            )  # Mark boiler offline on initial connection error
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
            if (current_time - self._polling_state.last_update_times.get(key, 0.0))
            >= interval.total_seconds()
        }
        retry_groups = {
            key: payloads[key]["payload_str"]
            for key, info in self._polling_state.failed_group_retry_info.items()
            if current_time >= info["next_retry_time"]
        }
        return due_groups | retry_groups

    def _get_log_level_for_failure(self) -> int:
        """Determine the appropriate log level based on consecutive failures."""
        return (
            logging.WARNING
            if self._polling_state.consecutive_failures >= self._log_level_threshold
            else logging.INFO
        )

    def _handle_successful_poll(self) -> None:
        """Handle the state update after a successful poll."""
        if self._polling_state.consecutive_failures > 0:
            _LIFECYCLE_LOGGER.info("Boiler back online. Resetting poll failures.")
        self._polling_state.consecutive_failures = 0
        self._polling_state.consecutive_connection_failures = 0
        self._polling_state.last_update_success_time = dt_util.utcnow()
        # Clear retry info for groups that have successfully updated.
        for group_key in list(self._polling_state.failed_group_retry_info):
            if self._polling_state.last_update_times.get(group_key, 0.0) > 0:
                del self._polling_state.failed_group_retry_info[group_key]
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

        self._polling_state.consecutive_failures += 1
        failures = self._polling_state.consecutive_failures
        threshold = self._log_level_threshold

        if failures == threshold:
            _LOGGER.warning(
                "Connection to host appears to be lost (failed %d consecutive times). Suppressing further group errors.",
                failures,
            )

        log_level_for_details = logging.DEBUG if failures >= threshold else logging.INFO

        for group_key in groups_in_cycle:
            info = self._polling_state.failed_group_retry_info.get(
                group_key, {"attempts": 0, "next_retry_time": 0.0}
            )
            info["attempts"] += 1
            delay = min(
                POLLING_RETRY_INITIAL_DELAY_S
                * (POLLING_RETRY_BACKOFF_FACTOR ** (info["attempts"] - 1)),
                POLLING_RETRY_MAX_DELAY_S,
            )
            info["next_retry_time"] = time.monotonic() + delay
            self._polling_state.failed_group_retry_info[group_key] = info

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
            self._polling_state.consecutive_connection_failures += 1
            failures = self._polling_state.consecutive_connection_failures
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
            # The consecutive_connection_failures counter is reset in _handle_successful_poll
            # when a successful poll occurs, ensuring the fallback logic persists during outages.
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
            self._on_connection_failure()
            result = self._handle_update_failure("connection", context={"error": err})
            if result is not None:
                return result

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

    def _unsubscribe_ping_callback(self) -> None:
        """Unsubscribe ping callback if set and reset the reference."""
        if self._ping_unsub:
            self._ping_unsub()
            self._ping_unsub = None

    async def async_stop_api_access_manager(self) -> None:
        """Gracefully stop the background HdgApiAccessManager task."""
        await self.api_access_manager.stop()
        self._unsubscribe_ping_callback()

    def _on_connection_failure(self) -> None:
        """Schedule a recurring ping when we lose connection."""
        interval = self.entry.options.get(
            CONF_FALLBACK_PING_INTERVAL, DEFAULT_FALLBACK_PING_INTERVAL
        )
        # If interval is zero, fallback pings are disabled.
        # This is intentional: setting CONF_FALLBACK_PING_INTERVAL to 0 disables pings.
        # nothing to do if user has disabled pings or we’re already scheduled
        if not interval or self._ping_unsub or not self._hostname:
            return

        # clamp once here if you still want min/max enforcement:
        interval = max(
            min(interval, MAX_FALLBACK_PING_INTERVAL), MIN_FALLBACK_PING_INTERVAL
        )
        self._ping_unsub = async_track_time_interval(
            self.hass, self._async_ping_and_refresh, timedelta(seconds=interval)
        )

    async def _async_ping_and_refresh(self, now: datetime) -> None:
        """Ping the boiler; on success cancel the track and force a refresh."""
        if self._hostname is None:
            _LOGGER.warning("Cannot ping: hostname is not available.")
            return
        try:
            if await async_execute_icmp_ping(self._hostname, timeout=3):
                _LIFECYCLE_LOGGER.info("Ping succeeded; forcing immediate refresh")
                # cancel further pings
                self._unsubscribe_ping_callback()
                await self.async_request_refresh()
        except Exception:
            _LOGGER.exception("Ping task failed; will retry on next interval")


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
