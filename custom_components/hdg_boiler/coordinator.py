"""Manage data fetching, updates, and API interactions for the HDG Bavaria Boiler integration."""

from __future__ import annotations

__version__ = "0.2.1"
__all__ = ["HdgDataUpdateCoordinator", "async_create_and_refresh_coordinator"]

import asyncio
import functools
import logging
import time
from datetime import datetime, timedelta
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import CALLBACK_TYPE, HassJob, HomeAssistant
from homeassistant.helpers.event import async_call_later
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .classes.polling_response_processor import HdgPollingResponseProcessor
from .const import (
    API_REQUEST_TYPE_GET_NODES_DATA,
    API_REQUEST_TYPE_SET_NODE_VALUE,
    COORDINATOR_FALLBACK_UPDATE_INTERVAL_MINUTES,
    COORDINATOR_MAX_CONSECUTIVE_FAILURES_BEFORE_FALLBACK,
    DOMAIN,
    INITIAL_SEQUENTIAL_INTER_GROUP_DELAY_S,
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


class HdgDataUpdateCoordinator(DataUpdateCoordinator[dict[str, Any]]):
    """Manage fetching data from the HDG boiler and coordinate updates."""

    update_interval: timedelta | None

    def __init__(
        self,
        hass: HomeAssistant,
        api_access_manager: HdgApiAccessManager,
        entry: ConfigEntry,
        log_level_threshold_for_connection_errors: int,
        hdg_entity_registry: HdgEntityRegistry,
    ):
        """Initialize the HdgDataUpdateCoordinator."""
        self.hass = hass
        self.api_access_manager = api_access_manager
        self.entry = entry
        self._log_level_threshold = log_level_threshold_for_connection_errors
        self.hdg_entity_registry = hdg_entity_registry

        self._initialize_state()
        self._validate_polling_config()
        self._initialize_scan_intervals()

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
        self._original_update_interval = self.update_interval
        self._polling_response_processor = HdgPollingResponseProcessor(self)
        _LOGGER.debug(
            "HdgDataUpdateCoordinator initialized. Update interval: %s",
            shortest_interval,
        )

    def _initialize_state(self) -> None:
        """Initialize all state-tracking attributes."""
        self.data: dict[str, Any] = {}
        self._initialize_polling_state()
        self._initialize_setter_state()
        self._boiler_online_event = asyncio.Event()
        self._set_boiler_online_status(True)

    def _initialize_polling_state(self) -> None:
        """Initialize attributes related to polling and error handling."""
        self.scan_intervals: dict[str, timedelta] = {}
        self._consecutive_poll_failures: int = 0
        self._fallback_update_interval = timedelta(
            minutes=COORDINATOR_FALLBACK_UPDATE_INTERVAL_MINUTES
        )
        self._max_consecutive_failures = (
            COORDINATOR_MAX_CONSECUTIVE_FAILURES_BEFORE_FALLBACK
        )
        self._failed_poll_group_retry_info: dict[str, dict[str, Any]] = {}
        self._last_update_times: dict[str, float] = dict.fromkeys(
            self.hdg_entity_registry.get_polling_group_order(), 0.0
        )

    def _initialize_setter_state(self) -> None:
        """Initialize attributes related to setting values."""
        self._last_set_times: dict[str, float] = {}
        self._pending_set_value_timers: dict[str, CALLBACK_TYPE] = {}
        self._optimistic_set_values: dict[str, Any] = {}
        self._optimistic_set_times: dict[str, float] = {}
        self._current_set_generations: dict[str, int] = {}
        self._set_value_locks: dict[str, asyncio.Lock] = {}

    def _set_boiler_online_status(self, is_online: bool) -> None:
        """Set and log the boiler's online status."""
        if getattr(self, "_boiler_considered_online", False) != is_online:
            _LIFECYCLE_LOGGER.info(
                "HDG Boiler transitioning to %s state.",
                "ONLINE" if is_online else "OFFLINE",
            )
            self._boiler_considered_online = is_online
            if is_online:
                self._boiler_online_event.set()
            else:
                self._boiler_online_event.clear()

    def _initialize_scan_intervals(self) -> None:
        """Initialize scan intervals for each polling group."""
        current_config = self.entry.options or self.entry.data
        for (
            group_key,
            payload,
        ) in self.hdg_entity_registry.get_polling_group_payloads().items():
            config_key = f"scan_interval_{group_key}"
            default_val = payload["default_scan_interval"]
            raw_val = current_config.get(config_key, str(default_val))
            try:
                scan_seconds = max(float(raw_val), MIN_SCAN_INTERVAL)
            except (ValueError, TypeError):
                scan_seconds = float(default_val)
            self.scan_intervals[group_key] = timedelta(seconds=scan_seconds)

    def _validate_polling_config(self) -> None:
        """Validate consistency of polling configurations."""
        order_keys = set(self.hdg_entity_registry.get_polling_group_order())
        payload_keys = set(self.hdg_entity_registry.get_polling_group_payloads().keys())
        if order_keys != payload_keys:
            raise ValueError("Polling group order and payload keys mismatch.")

    @property
    def last_update_times_public(self) -> dict[str, float]:
        """Return last successful update times for polling groups."""
        return self._last_update_times

    @property
    def boiler_is_online(self) -> bool:
        """Return True if the boiler is considered online."""
        return self._boiler_considered_online

    async def _fetch_group_data(
        self, group_key: str, payload_str: str, priority: ApiPriority
    ) -> bool:
        """Fetch and process data for a single polling group."""
        try:
            fetched_data = await self.api_access_manager.submit_request(
                priority=priority,
                coroutine=self.api_access_manager._api_client.async_get_nodes_data,
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
    ) -> tuple[bool, bool]:
        """Fetch data for multiple polling groups sequentially."""
        any_success, any_conn_error = False, False
        for i, (group_key, payload_str) in enumerate(groups):
            try:
                if await self._fetch_group_data(group_key, payload_str, priority):
                    self._last_update_times[group_key] = time.monotonic()
                    any_success = True
            except HdgApiConnectionError:
                any_conn_error = True
            if i < len(groups) - 1:
                await asyncio.sleep(INITIAL_SEQUENTIAL_INTER_GROUP_DELAY_S)
        return any_success, any_conn_error

    async def async_config_entry_first_refresh(self) -> None:
        """Perform initial sequential data refresh for all polling groups."""
        _LIFECYCLE_LOGGER.info("Initiating first data refresh for %s.", self.name)
        all_groups = [
            (gk, p["payload_str"])
            for gk, p in self.hdg_entity_registry.get_polling_group_payloads().items()
        ]
        any_success, any_conn_error = await self._sequentially_fetch_groups(
            all_groups, ApiPriority.MEDIUM
        )

        if not any_success:
            self._set_boiler_online_status(False)
            msg = f"Initial data refresh failed for {self.name}."
            if any_conn_error:
                msg += " Connection errors encountered."
            raise UpdateFailed(msg)

        self._set_boiler_online_status(True)
        _LIFECYCLE_LOGGER.info("First data refresh for %s complete.", self.name)
        self.async_set_updated_data(self.data)
        await asyncio.sleep(POST_INITIAL_REFRESH_COOLDOWN_S)

    def _get_groups_to_fetch(self, current_time: float) -> dict[str, str]:
        """Identify all polling groups that are due for an update or retry."""
        due_groups = {
            key: payload["payload_str"]
            for key, payload in self.hdg_entity_registry.get_polling_group_payloads().items()
            if (current_time - self._last_update_times.get(key, 0.0))
            >= self.scan_intervals[key].total_seconds()
        }
        retry_groups = {
            key: self.hdg_entity_registry.get_polling_group_payloads()[key][
                "payload_str"
            ]
            for key, info in self._failed_poll_group_retry_info.items()
            if current_time >= info["next_retry_time"]
        }
        return due_groups | retry_groups

    def _update_failed_group_retry_info(self, group_key: str) -> None:
        """Update retry metadata for a failed group."""
        info = self._failed_poll_group_retry_info.get(group_key, {"attempts": 0})
        info["attempts"] += 1
        delay = min(
            POLLING_RETRY_INITIAL_DELAY_S
            * (POLLING_RETRY_BACKOFF_FACTOR ** (info["attempts"] - 1)),
            POLLING_RETRY_MAX_DELAY_S,
        )
        info["next_retry_time"] = time.monotonic() + delay
        self._failed_poll_group_retry_info[group_key] = info
        _LOGGER.log(
            logging.INFO
            if self._consecutive_poll_failures < self._log_level_threshold
            else logging.WARNING,
            "Error for group '%s'. Attempt %s, next retry in %.0fs.",
            group_key,
            info["attempts"],
            delay,
        )
        if info["attempts"] >= POLLING_RETRY_MAX_ATTEMPTS:
            _LIFECYCLE_LOGGER.warning(
                "Group '%s' reached max retry attempts.", group_key
            )

    def _process_failed_poll_cycle(self, groups_in_cycle: list[str]) -> None:
        """Handle a completely failed polling cycle."""
        self._consecutive_poll_failures += 1
        self._set_boiler_online_status(False)
        for group_key in groups_in_cycle:
            self._update_failed_group_retry_info(group_key)

        if self._consecutive_poll_failures >= self._max_consecutive_failures:
            self.update_interval = self._fallback_update_interval
            _LIFECYCLE_LOGGER.warning(
                "Boiler offline. Switching to fallback interval: %s",
                self.update_interval,
            )
            raise UpdateFailed("Persistent connection errors.")

    def _process_successful_poll_cycle(self) -> None:
        """Handle a partially or fully successful polling cycle."""
        self._set_boiler_online_status(True)
        if self._consecutive_poll_failures > 0:
            _LIFECYCLE_LOGGER.info("Boiler back online. Resetting poll failures.")
        self._consecutive_poll_failures = 0

        for group_key in list(self._failed_poll_group_retry_info.keys()):
            if self._last_update_times.get(group_key, 0.0) > 0.0:
                del self._failed_poll_group_retry_info[group_key]

        if self.update_interval == self._fallback_update_interval:
            self.update_interval = self._original_update_interval
            _LIFECYCLE_LOGGER.info(
                "Polling successful. Restoring original interval: %s",
                self.update_interval,
            )

    async def _async_update_data(self) -> dict[str, Any]:
        """Fetch data for all due polling groups."""
        groups_to_fetch = self._get_groups_to_fetch(time.monotonic())
        if not groups_to_fetch:
            return self.data

        any_success, _ = await self._sequentially_fetch_groups(
            list(groups_to_fetch.items()), ApiPriority.LOW
        )

        if not any_success:
            self._process_failed_poll_cycle(list(groups_to_fetch.keys()))
        else:
            self._process_successful_poll_cycle()

        return self.data

    async def async_set_node_value(
        self, node_id: str, value: str, entity_name_for_log: str, debounce_delay: float
    ) -> bool:
        """Queue a node value to be set on the boiler with debouncing."""
        if not isinstance(value, str):
            raise TypeError(f"Value for {entity_name_for_log} must be a string.")

        generation = self._current_set_generations.get(node_id, 0) + 1
        self._current_set_generations[node_id] = generation
        self._optimistic_set_values[node_id] = value
        self._optimistic_set_times[node_id] = time.monotonic()

        if node_id in self._pending_set_value_timers:
            self._pending_set_value_timers.pop(node_id)()

        job_target = functools.partial(
            self._process_debounced_set_value,
            node_id=node_id,
            value=value,
            entity_name_for_log=entity_name_for_log,
            scheduled_generation=generation,
        )
        self._pending_set_value_timers[node_id] = async_call_later(
            self.hass, debounce_delay, HassJob(job_target, cancel_on_shutdown=True)
        )
        return True

    async def _process_debounced_set_value(
        self,
        _: datetime,
        node_id: str,
        value: str,
        entity_name_for_log: str,
        scheduled_generation: int,
    ) -> None:
        """Process the debounced set value and send it to the API."""
        del self._pending_set_value_timers[node_id]
        lock = self._set_value_locks.setdefault(node_id, asyncio.Lock())
        async with lock:
            if scheduled_generation != self._current_set_generations.get(node_id):
                _USER_ACTION_LOGGER.debug(
                    "Skipping stale set request for %s.", entity_name_for_log
                )
                return

            try:
                success = await self.api_access_manager.submit_request(
                    priority=ApiPriority.HIGH,
                    coroutine=self.api_access_manager._api_client.async_set_node_value,
                    request_type=API_REQUEST_TYPE_SET_NODE_VALUE,
                    context_key=node_id,
                    node_id=node_id,
                    value=value,
                    current_value=self.data.get(node_id),
                )
                if success:
                    self.data[node_id] = value
                    self._last_set_times[node_id] = time.monotonic()
                    _LOGGER.info(
                        "Successfully set %s to '%s'.", entity_name_for_log, value
                    )
                    self.async_set_updated_data(self.data)
                else:
                    _LOGGER.error(
                        "Failed to set %s to '%s'.", entity_name_for_log, value
                    )
            except HdgApiError as e:
                _LOGGER.error("API error setting %s: %s", entity_name_for_log, e)
            finally:
                self._optimistic_set_values.pop(node_id, None)
                self._optimistic_set_times.pop(node_id, None)

    async def async_stop_api_access_manager(self) -> None:
        """Gracefully stop the background HdgApiAccessManager task."""
        await self.api_access_manager.stop()


async def async_create_and_refresh_coordinator(
    hass: HomeAssistant,
    api_access_manager: HdgApiAccessManager,
    entry: ConfigEntry,
    log_level_threshold_for_connection_errors: int,
    hdg_entity_registry: HdgEntityRegistry,
) -> HdgDataUpdateCoordinator:
    """Create, initialize, and perform the first data refresh for the coordinator."""
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
