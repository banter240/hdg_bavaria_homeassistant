"""Manage data fetching, updates, and API interactions for the HDG Bavaria Boiler integration."""

from __future__ import annotations

__all__ = ["HdgDataUpdateCoordinator", "async_create_and_refresh_coordinator"]

import asyncio
import logging
import time
from datetime import timedelta
from typing import Any
from urllib.parse import urlparse

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import CALLBACK_TYPE, HomeAssistant, callback
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.event import async_call_later
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.util import dt as dt_util

from .api import HdgApiClient
from .classes.polling_response_processor import HdgPollingResponseProcessor
from .const import (
    CONF_LOG_LEVEL_THRESHOLD_FOR_PREEMPTION_ERRORS,
    DEFAULT_LOG_LEVEL_THRESHOLD_FOR_PREEMPTION_ERRORS,
    DEFAULT_SET_VALUE_DEBOUNCE_DELAY_S,
    DOMAIN,
    MAX_CONCURRENT_POLL_REQUESTS,
    MIN_SCAN_INTERVAL,
    POLLING_RETRY_BACKOFF_FACTOR,
    POLLING_RETRY_INITIAL_DELAY_S,
    POLLING_RETRY_MAX_DELAY_S,
    POST_INITIAL_REFRESH_COOLDOWN_S,
)
from .exceptions import (
    HdgApiConnectionError,
    HdgApiError,
    HdgApiPreemptedError,
    HdgApiResponseError,
)
from .helpers.api_access_manager import ApiPriority, HdgApiAccessManager
from .helpers.optimistic_manager import HdgOptimisticManager
from .helpers.logging_utils import (
    _LIFECYCLE_LOGGER,
    _LOGGER,
    _USER_ACTION_LOGGER,
)
from .models import CommandType, HdgCommand, PollingState
from .registry import HdgEntityRegistry

_PLATFORM_SUFFIXES = ["_sensor", "_binary_sensor", "_number", "_select", "_switch"]


def _monotonic_to_utc_iso(timestamp: float) -> str:
    """Convert a monotonic timestamp to a UTC ISO format string."""
    diff = timestamp - time.monotonic()
    utc_dt = dt_util.utcnow() + timedelta(seconds=diff)
    return str(utc_dt.isoformat())


class HdgDataUpdateCoordinator(DataUpdateCoordinator[dict[str, Any]]):
    """Class to manage fetching data from the HDG Boiler API."""

    def __init__(
        self,
        hass: HomeAssistant,
        api_client: HdgApiClient,
        api_access_manager: HdgApiAccessManager,
        entry: ConfigEntry,
        log_level_threshold_for_connection_errors: int,
        error_threshold: int,
        hdg_entity_registry: HdgEntityRegistry,
    ) -> None:
        """Initialize the coordinator."""
        self.entry = entry
        self.hdg_entity_registry = hdg_entity_registry
        self.api_client = api_client
        self.api_access_manager = api_access_manager

        self._log_level_threshold = log_level_threshold_for_connection_errors
        self._error_threshold = error_threshold

        prepared_base_url = self.api_client.base_url
        self._hostname = urlparse(prepared_base_url).hostname
        super().__init__(
            hass,
            _LOGGER,
            name=f"{DOMAIN}_{self._hostname}",
            update_interval=timedelta(seconds=MIN_SCAN_INTERVAL),
        )

        self._polling_response_processor = HdgPollingResponseProcessor(self)
        self._active_node_ids: set[str] = (
            self.hdg_entity_registry.get_default_active_node_ids()
        )

        self._polling_state = PollingState()
        self.optimistic = HdgOptimisticManager()

        # Pending debounce timers and their last value: {node_id: (cancel_fn, value, name)}
        self._pending_set_timers: dict[str, tuple[CALLBACK_TYPE, str, str]] = {}

        # DataUpdateCoordinator initialises self.data to None; we need a dict
        # from the very first poll so update_node() can write into it safely.
        self.data: dict[str, Any] = {}

    @property
    def scan_intervals(self) -> dict[str, timedelta]:
        """Return the effective scan intervals for each polling group."""
        return {
            gk: timedelta(seconds=p["default_scan_interval"])
            for gk, p in self.hdg_entity_registry.get_polling_group_payloads().items()
        }

    def get_diagnostics(self) -> dict[str, Any]:
        """Return diagnostic information for the coordinator."""
        return {
            "name": self.name,
            "hostname": self._hostname,
            "consecutive_failures": self._polling_state.consecutive_failures,  # gitleaks:allow
            "last_update_success": self._polling_state.last_update_success_time,  # gitleaks:allow
            "active_node_count": len(self._active_node_ids),
            "polling_group_status": {
                k: {
                    "last_update_monotonic": self._polling_state.last_update_times.get(  # gitleaks:allow
                        k, 0.0
                    ),
                    "last_update_utc": (
                        _monotonic_to_utc_iso(self._polling_state.last_update_times[k])
                        if k in self._polling_state.last_update_times
                        else None
                    ),
                }
                for k in self.hdg_entity_registry.get_polling_group_payloads()
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
        optimized_nodes, active_count, total_count = (
            self.hdg_entity_registry.get_optimized_payload_for_group(
                group_key, self._active_node_ids
            )
        )

        if optimized_nodes is None:
            _LOGGER.debug("Skipping poll for group '%s': no active nodes.", group_key)
            return True

        _LOGGER.debug(
            "Payload for group '%s': %d/%d nodes active.",
            group_key,
            active_count,
            total_count,
        )

        try:
            cmd = HdgCommand(
                cmd_type=CommandType.GET_NODES,
                context_key=group_key,
                node_ids=optimized_nodes,
            )
            fetched_data = await self.api_access_manager.submit_request(
                priority=priority,
                command=cmd,
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

    async def _concurrently_fetch_groups(
        self, groups: list[str], priority: ApiPriority
    ) -> bool:
        """Fetch data for multiple polling groups concurrently with a limit."""
        semaphore = asyncio.Semaphore(MAX_CONCURRENT_POLL_REQUESTS)

        async def fetch_with_semaphore(group_key: str) -> tuple[str, bool]:
            async with semaphore:
                try:
                    success = await self._fetch_group_data(group_key, priority)
                    return group_key, success
                except HdgApiConnectionError:
                    raise
                except Exception:
                    _LOGGER.exception(
                        "Unhandled exception fetching group '%s'.", group_key
                    )
                    return group_key, False

        tasks = [fetch_with_semaphore(gk) for gk in groups]
        try:
            results = await asyncio.gather(*tasks)
        except HdgApiConnectionError:
            raise

        any_success = any(r[1] for r in results)

        for group_key, success in results:
            if success:
                self._polling_state.last_update_times[group_key] = time.monotonic()

        return any_success

    def _sync_active_nodes_from_registry(self) -> None:
        """Pre-populate active nodes from the HA entity registry.

        Entities with entity_registry_enabled_default=False (e.g. lager sensors)
        are excluded from get_default_active_node_ids(). If the user previously
        enabled them manually they would be missed on the first poll — which sets
        the 24 h group timer — leaving them unavailable until the next day.
        This method walks the registry so any already-enabled entity is polled
        on the very first cycle, regardless of its enabled-by-default flag.
        """
        ent_reg = er.async_get(self.hass)
        added = 0
        for reg_entry in er.async_entries_for_config_entry(
            ent_reg, self.entry.entry_id
        ):
            if not reg_entry.disabled:
                if (
                    node_id
                    := self.hdg_entity_registry.resolve_node_id_from_entity_entry(
                        reg_entry
                    )
                ):
                    self._active_node_ids.add(node_id)
                    added += 1
        if added:
            _LIFECYCLE_LOGGER.debug(
                "Pre-populated %d active nodes from entity registry.", added
            )

    async def async_config_entry_first_refresh(self) -> None:
        """Perform initial sequential data refresh for all polling groups."""
        self._sync_active_nodes_from_registry()
        _LIFECYCLE_LOGGER.info("Initiating first data refresh for %s.", self.name)
        all_groups = list(self.hdg_entity_registry.get_polling_group_payloads().keys())
        try:
            any_success = await self._concurrently_fetch_groups(
                all_groups, ApiPriority.MEDIUM
            )
            if not any_success:
                raise UpdateFailed(f"Initial data refresh failed for {self.name}.")
        except HdgApiConnectionError as err:
            self._set_boiler_online_status(False)
            raise UpdateFailed(
                f"Initial data refresh failed for {self.name} due to connection error: {err}"
            ) from err

        self._set_boiler_online_status(True)
        _LIFECYCLE_LOGGER.info("First data refresh for %s complete.", self.name)
        self.async_set_updated_data(self.data)
        await asyncio.sleep(POST_INITIAL_REFRESH_COOLDOWN_S)

    def _get_groups_to_fetch(self, current_time: float) -> set[str]:
        """Identify all polling groups that are due for an update or retry."""
        scan_intervals = self.scan_intervals
        due_groups = {
            key
            for key, interval in scan_intervals.items()
            if (current_time - self._polling_state.last_update_times.get(key, 0.0))
            >= interval.total_seconds()
        }
        retry_groups = {
            key
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
        for group_key in list(self._polling_state.failed_group_retry_info):
            if self._polling_state.last_update_times.get(group_key, 0.0) > 0:
                del self._polling_state.failed_group_retry_info[group_key]

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
                "Fetch for group '%s' failed (attempt %d). Retrying in %ds.",
                group_key,
                info["attempts"],
                delay,
            )

    async def _async_update_data(self) -> dict[str, Any]:
        """Fetch data for all due polling groups."""
        groups_to_fetch = self._get_groups_to_fetch(time.monotonic())
        if not groups_to_fetch:
            return self.data

        try:
            any_success = await self._concurrently_fetch_groups(
                list(groups_to_fetch), ApiPriority.LOW
            )
            self._set_boiler_online_status(any_success)
            self._update_polling_status(any_success, list(groups_to_fetch))
            self.optimistic.cleanup()

        except HdgApiConnectionError as err:
            self._on_connection_failure()
            result = self._handle_update_failure("connection", context={"error": err})
            if result is not None:
                return result

        return self.data

    def _on_connection_failure(self) -> None:
        """Handle connection failure."""
        self._polling_state.consecutive_connection_failures += 1
        self._set_boiler_online_status(False)

    def _set_boiler_online_status(self, online: bool) -> None:
        """Update the internal online state of the boiler."""
        pass

    def _handle_update_failure(
        self, failure_type: str, context: dict[str, Any] | None = None
    ) -> dict[str, Any] | None:
        """Return cached data on failure to avoid clearing entities."""
        return self.data

    def update_node(self, node_id: str, value: Any) -> None:
        """Write a single node value into the coordinator data store.

        All writes to coordinator.data go through here so there is one place
        to add guards, metrics, or notifications in the future.
        """
        self.data[node_id] = value

    def register_node(self, node_id: str) -> None:
        """Mark a node as active so it is included in polling payloads."""
        self._active_node_ids.add(node_id)

    def unregister_node(self, node_id: str) -> None:
        """Remove a node from active polling (entity disabled or removed)."""
        self._active_node_ids.discard(node_id)

    def get_optimistic_value(self, node_id: str) -> str | None:
        """Return the pending optimistic value for a node, or None if expired/unset.

        Entities call this to show immediate UI feedback while waiting for API
        confirmation. Falls back to coordinator.data on None.
        """
        return self.optimistic.get(node_id)

    async def async_set_node_value(
        self, node_id: str, value: str, entity_name_for_log: str
    ) -> tuple[bool, str | None]:
        """Queue a debounced SET_NODE request and update optimistic state immediately.

        Rapid calls for the same node (e.g. slider drag) collapse: each new call
        cancels the previous pending timer so only the last value reaches the API.
        The optimistic state is updated on every call so the UI always reflects
        the latest user input without waiting for the debounce window.
        """
        _USER_ACTION_LOGGER.info(
            "User requested %s → '%s'.", entity_name_for_log, value
        )

        if pending := self._pending_set_timers.pop(node_id, None):
            pending[0]()

        self.optimistic.set(node_id, value)
        self.async_set_updated_data(self.data)

        @callback
        def _fire_set(_now: Any = None, _nid: str = node_id) -> None:
            """Debounce timer expired — dispatch the actual API request."""
            self._pending_set_timers.pop(_nid, None)
            task = self.hass.async_create_task(
                self._execute_set_request(_nid, value, entity_name_for_log),
                name=f"hdg_set_{_nid}",
            )
            task.add_done_callback(lambda _: None)

        cancel = async_call_later(
            self.hass, DEFAULT_SET_VALUE_DEBOUNCE_DELAY_S, _fire_set
        )
        self._pending_set_timers[node_id] = (cancel, value, entity_name_for_log)
        return True, value

    async def _execute_set_request(
        self, node_id: str, value: str, entity_name_for_log: str
    ) -> None:
        """Execute the SET_NODE API call, persist on success, rollback on failure."""
        old_value = self.data.get(node_id)
        try:
            cmd = HdgCommand(
                cmd_type=CommandType.SET_NODE,
                context_key=node_id,
                node_id=node_id,
                value=value,
            )
            success = await self.api_access_manager.submit_request(
                priority=ApiPriority.HIGH,
                command=cmd,
            )
            if success:
                self.update_node(node_id, value)
                _USER_ACTION_LOGGER.info(
                    "Set %s to '%s' confirmed.", entity_name_for_log, value
                )
            else:
                _LOGGER.error(
                    "Set %s to '%s' failed (API returned false).",
                    entity_name_for_log,
                    value,
                )
        except Exception as err:
            _LOGGER.error(
                "Error setting %s to '%s': %s", entity_name_for_log, value, err
            )
            if old_value is not None:
                self.update_node(node_id, old_value)
        finally:
            self.optimistic.clear(node_id)
            self.async_set_updated_data(self.data)

    async def async_stop(self) -> None:
        """Stop the coordinator and cancel any pending debounce timers."""
        for cancel_fn, _, _ in self._pending_set_timers.values():
            cancel_fn()
        self._pending_set_timers.clear()
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
