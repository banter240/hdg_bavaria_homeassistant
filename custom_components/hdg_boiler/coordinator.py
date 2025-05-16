"""
DataUpdateCoordinator for the HDG Bavaria Boiler integration.

The HdgDataUpdateCoordinator is central to the integration. It periodically fetches
data from the HDG boiler API in predefined groups, manages update intervals for these
groups, and makes the latest data available to all entities. It also handles
initial data population and error management during data fetching.
"""

__version__ = "0.8.0"

import asyncio
import logging
from datetime import timedelta, datetime
from typing import Any, Dict

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.util import dt as dt_util

from .const import (
    DOMAIN,
    HDG_NODE_PAYLOADS,
    POLLING_GROUP_ORDER,
    NodeGroupPayload,
    CONF_ENABLE_DEBUG_LOGGING,
    DEFAULT_ENABLE_DEBUG_LOGGING,
)
from .api import HdgApiClient, HdgApiConnectionError, HdgApiResponseError

_LOGGER = logging.getLogger(DOMAIN)

# Delay (in seconds) between fetching data groups sequentially.
# Used during initial setup and for due groups in regular updates
# to prevent overwhelming the boiler's API.
INITIAL_SEQUENTIAL_INTER_GROUP_DELAY_S: float = 2.0


class HdgDataUpdateCoordinator(DataUpdateCoordinator[Dict[str, Any]]):
    """
    Manages fetching HDG boiler data, stores it, and provides updates to entities.

    Employs a two-phase data fetching:
    1.  Initial Fetch: Sequentially fetches all groups on startup with delays.
    2.  Periodic Updates: Checks due groups; fetches sequentially if multiple are due.
    """

    def __init__(
        self,
        hass: HomeAssistant,
        api_client: HdgApiClient,
        entry: ConfigEntry,
    ):
        """
        Initialize the data update coordinator.

        Args:
            hass: The Home Assistant instance.
            api_client: An instance of the HdgApiClient for API communication.
            entry: Config entry, used for user-configured options (scan intervals, host IP).
        """
        self.hass = hass
        self.api_client = api_client
        self.entry = entry

        # Use options if available (user-configured), otherwise initial config data.
        current_config = self.entry.options or self.entry.data

        # Store scan interval (timedelta) for each polling group.
        self.scan_intervals: Dict[str, timedelta] = {}
        # Populate scan intervals from configuration, applying defaults.
        for group_key, payload_details in HDG_NODE_PAYLOADS.items():
            config_key_for_scan = payload_details["config_key_scan_interval"]
            default_scan_val = payload_details["default_scan_interval"]
            self.scan_intervals[group_key] = timedelta(
                seconds=current_config.get(config_key_for_scan, default_scan_val)
            )

        # Timestamp (`hass.loop.time()`) of last successful update per group; determines next poll.
        self._last_update_times: Dict[str, float] = {}
        # Flag for detailed debug logging of polling cycles.
        self._enable_debug_logging = current_config.get(
            CONF_ENABLE_DEBUG_LOGGING, DEFAULT_ENABLE_DEBUG_LOGGING
        )

        # Ensure all groups are polled on first refresh by setting last update times to 0.0.
        self._initialize_last_update_times()

        # Coordinator's main update interval is the shortest group scan interval.
        # Ensures `_async_update_data` is called frequently enough.
        shortest_interval = (
            min(self.scan_intervals.values()) if self.scan_intervals else timedelta(seconds=60)
        )

        super().__init__(
            hass,
            _LOGGER,
            name=f"{DOMAIN} ({self.entry.title})",  # Descriptive name for logging.
            update_interval=shortest_interval,
        )
        # Data store for fetched node values, keyed by base HDG node ID.
        self.data: Dict[str, Any] = {}
        _LOGGER.debug(
            f"HdgDataUpdateCoordinator for '{self.entry.title}' initialized. "
            f"Shortest interval: {shortest_interval}."
        )

    def _initialize_last_update_times(self) -> None:
        """
        Initialize _last_update_times for all polling groups to 0.0.

        Ensures all groups are polled during the first refresh cycle, as 0.0
        (epoch for `hass.loop.time()`) will make them immediately due.
        """
        for group_key in POLLING_GROUP_ORDER:
            if group_key in self.scan_intervals:
                self._last_update_times[group_key] = 0.0
            else:
                _LOGGER.warning(
                    f"Polling group key '{group_key}' from POLLING_GROUP_ORDER not found in scan_intervals. "  # pragma: no cover
                    f"Initialization of last update time will skip this group."  # pragma: no cover
                )

    async def _fetch_group_data(self, group_key: str, payload_config: NodeGroupPayload) -> bool:
        """
        Fetch data for a single polling group and update the internal `self.data` store.

        Args:
            group_key: Identifier for the polling group.
            payload_config: Configuration for the group, including API payload.

        Returns:
            True if data fetched and processed successfully.
            False on API response error (non-connection error).

        Raises:
            HdgApiConnectionError: On connection issues; propagated to caller.
        """
        payload_str = payload_config["payload_str"]
        start_time_group_fetch = self.hass.loop.time()
        if self._enable_debug_logging:
            # Log with local time for easier human correlation.
            # `hass.loop.time()` for duration, `dt_util` for display.
            _LOGGER.info(
                f"INITIATING FETCH for group: {group_key} at {dt_util.as_local(dt_util.utcnow())}"
            )
        try:
            fetched_data_list = await self.api_client.async_get_nodes_data(payload_str)

            if fetched_data_list is not None:
                # Store fetched data, using base node ID (suffix stripped) as key.
                # API returns list of dicts: {"id": "nodeID_suffix", "text": "value"}.
                for item in fetched_data_list:  # item is Dict[str, Any] with "id" and "text"
                    node_id_with_suffix = str(item["id"])
                    node_id_clean = node_id_with_suffix.rstrip("TUVWXY")
                    self.data[node_id_clean] = item["text"]
                _LOGGER.debug(
                    f"Successfully processed data for HDG group: {group_key}. {len(fetched_data_list)} items."
                )
                end_time_group_fetch = self.hass.loop.time()
                if self._enable_debug_logging:
                    _LOGGER.info(
                        f"COMPLETED FETCH for group: {group_key} at {dt_util.as_local(dt_util.utcnow())}. "
                        f"Duration: {end_time_group_fetch - start_time_group_fetch:.2f}s"
                    )
                return True
            else:
                # Should not be reached if api_client raises error or returns list.
                # Logged to identify unexpected api_client behavior.
                _LOGGER.warning(
                    f"Polling for group {group_key} returned None from api_client without raising an error."
                )  # pragma: no cover
                return False

        except HdgApiConnectionError as conn_err:
            # Critical connection errors (timeout, host unreachable) are propagated.
            # Caller (e.g., _async_update_data) will handle by raising UpdateFailed.
            end_time_group_fetch_err = self.hass.loop.time()
            if self._enable_debug_logging:  # pragma: no cover
                _LOGGER.warning(
                    f"CONNECTION ERROR during fetch for group: {group_key} at {dt_util.as_local(dt_util.utcnow())}. Duration: {end_time_group_fetch_err - start_time_group_fetch:.2f}s. Error: {conn_err}"
                )
            raise
        except HdgApiResponseError as err:
            # API response errors (bad status, malformed JSON) for this group are logged.
            # Return False, allowing coordinator to attempt updates for other groups.
            _LOGGER.warning(  # Changed from error to warning, as it's a per-group issue
                f"API response error polling group {group_key}: {err}. Data for this group may be stale."
            )  # pragma: no cover
            end_time_group_fetch_err = self.hass.loop.time()
            if self._enable_debug_logging:  # pragma: no cover
                _LOGGER.warning(
                    f"API RESPONSE ERROR during fetch for group: {group_key} at {dt_util.as_local(dt_util.utcnow())}. Duration: {end_time_group_fetch_err - start_time_group_fetch:.2f}s. Error: {err}"
                )
            return False
        except Exception as err:
            # Catch-all for other unexpected errors during this group's fetch.
            _LOGGER.exception(
                f"Unexpected error polling group {group_key}: {err}"
            )  # pragma: no cover
            end_time_group_fetch_err = self.hass.loop.time()
            if self._enable_debug_logging:  # pragma: no cover
                _LOGGER.error(
                    f"UNEXPECTED ERROR during fetch for group: {group_key} at {dt_util.as_local(dt_util.utcnow())}. Duration: {end_time_group_fetch_err - start_time_group_fetch:.2f}s. Error: {err}"
                )
            return False  # pragma: no cover

    async def async_config_entry_first_refresh(self) -> None:
        """
        Perform the first data refresh sequentially for all groups on HA setup.

        Fetches data for all defined polling groups one by one, with a delay,
        to populate initial state and avoid overwhelming the boiler's API.
        """
        # Record start time for performance monitoring if debug logging is enabled.
        start_time_first_refresh = self.hass.loop.time()
        if self._enable_debug_logging:
            _LOGGER.info(
                f"INITIATING async_config_entry_first_refresh for {self.name} at {dt_util.as_local(dt_util.utcnow())} with {INITIAL_SEQUENTIAL_INTER_GROUP_DELAY_S}s inter-group delay..."
            )
        # Flags to track overall success and connection issues during initial fetch.
        # `initial_data_items_fetched_count` for logging.
        any_group_failed_connection = False
        initial_data_items_fetched_count = 0

        for i, group_key in enumerate(POLLING_GROUP_ORDER):
            payload_config = HDG_NODE_PAYLOADS.get(group_key)
            if not payload_config:
                _LOGGER.warning(
                    f"Skipping initial poll for group '{group_key}': not defined in HDG_NODE_PAYLOADS."
                )  # pragma: no cover
                continue

            _LOGGER.debug(f"Initial sequential poll for group: {group_key}")
            try:
                success = await self._fetch_group_data(group_key, payload_config)
                if success:
                    self._last_update_times[group_key] = self.hass.loop.time()
                    initial_data_items_fetched_count += len(payload_config.get("nodes", []))
                    _LOGGER.debug(f"Initial poll for group {group_key} successful.")
                else:
                    # Group fetch failed without a connection error (e.g., HdgApiResponseError).
                    _LOGGER.warning(
                        f"Initial poll for group {group_key} reported failure (e.g., API response error)."
                    )  # pragma: no cover
            except HdgApiConnectionError as err:
                # Mark connection failure; overall failure assessed after all groups.
                _LOGGER.warning(  # Changed from error to warning, as UpdateFailed will be raised later if needed
                    f"Initial poll for group {group_key} failed with connection error: {err}"
                )
                any_group_failed_connection = True
            except Exception as err:
                _LOGGER.exception(
                    f"Unexpected error during initial poll of group {group_key}: {err}"
                )
                any_group_failed_connection = (  # pragma: no cover
                    True  # Treat unexpected errors as connection issues for setup.
                )

            if i < len(POLLING_GROUP_ORDER) - 1:
                # Delay before polling next group to avoid overwhelming the API.
                _LOGGER.debug(
                    f"Waiting {INITIAL_SEQUENTIAL_INTER_GROUP_DELAY_S}s before polling next group."
                )
                await asyncio.sleep(INITIAL_SEQUENTIAL_INTER_GROUP_DELAY_S)

        # If no data fetched AND a connection failed, raise UpdateFailed.
        # Indicates fundamental problem (e.g., boiler offline, wrong IP).
        if not self.data and any_group_failed_connection:
            _LOGGER.error(
                f"Initial data refresh for {self.name} failed to retrieve any data due to connection issues. "
                "Setup will be retried by Home Assistant."
            )
            raise UpdateFailed(
                "Failed to connect to HDG boiler during initial setup and retrieve any data."
            )

        # If no data fetched, but no connection errors (e.g., API returned empty lists
        # or all groups had HdgApiResponseErrors), log a warning.
        if not self.data and not any_group_failed_connection:
            _LOGGER.warning(
                f"Initial data refresh for {self.name} completed, but no data was fetched from any group. "
                "This might be normal if the boiler is offline or payloads are empty."  # pragma: no cover
            )

        end_time_first_refresh = self.hass.loop.time()
        if self._enable_debug_logging:
            _LOGGER.info(
                f"COMPLETED async_config_entry_first_refresh for {self.name} at {dt_util.as_local(dt_util.utcnow())}. "
                f"Duration: {end_time_first_refresh - start_time_first_refresh:.2f}s. "
                f"Approx {initial_data_items_fetched_count} node values potentially updated. Total items in coordinator.data: {len(self.data if self.data else [])}"
            )
        self.async_set_updated_data(self.data)

    async def _async_update_data(self) -> Dict[str, Any]:
        """
        Fetch data for due polling groups. Called periodically by base class.

        Checks each group's due status based on its scan interval and last update.
        If multiple groups are due, they are fetched sequentially with a delay
        to reduce peak load on the boiler's API.
        """
        # Refresh debug logging setting from options in case of user changes.
        self._enable_debug_logging = self.entry.options.get(
            CONF_ENABLE_DEBUG_LOGGING, DEFAULT_ENABLE_DEBUG_LOGGING
        )
        # Record start time for performance monitoring of the update cycle.
        start_time_update_cycle = self.hass.loop.time()
        if self._enable_debug_logging:
            _LOGGER.info(
                f"INITIATING _async_update_data cycle at {dt_util.as_local(dt_util.utcnow())}"
            )

        current_time_for_due_check = self.hass.loop.time()
        # Log cycle start with a human-readable local timestamp.
        _LOGGER.debug(
            f"Coordinator _async_update_data cycle started at {datetime.fromtimestamp(current_time_for_due_check, tz=dt_util.get_default_time_zone())}"
        )

        # List to hold (group_key, payload_config) for groups due for update.
        due_groups_to_fetch_sequentially: list[tuple[str, NodeGroupPayload]] = []

        # --- Determine which polling groups are due ---
        for group_key in POLLING_GROUP_ORDER:
            payload_config = HDG_NODE_PAYLOADS.get(group_key)

            if not payload_config or group_key not in self.scan_intervals:
                # Should not happen if POLLING_GROUP_ORDER and HDG_NODE_PAYLOADS are consistent.
                _LOGGER.debug(
                    f"Skipping group '{group_key}': not defined in HDG_NODE_PAYLOADS or scan_intervals."
                )  # pragma: no cover
                continue

            group_scan_interval_seconds = self.scan_intervals[group_key].total_seconds()
            last_update_time_for_group = self._last_update_times.get(group_key, 0)

            # A group is due if elapsed time since last successful update
            # meets or exceeds its scan interval.
            if (
                current_time_for_due_check - last_update_time_for_group
            ) >= group_scan_interval_seconds:
                due_groups_to_fetch_sequentially.append((group_key, payload_config))
            else:
                # Log skipped groups and approx. time until next poll.
                _LOGGER.debug(
                    f"Skipping poll for HDG group: {group_key} (Next in approx. {max(0, group_scan_interval_seconds - (current_time_for_due_check - last_update_time_for_group)):.0f}s)"
                )

        # --- Process due groups or return if none are due ---
        if not due_groups_to_fetch_sequentially:
            # No groups due; log and return existing data.
            _LOGGER.debug("No polling groups were due for an update in this coordinator cycle.")
            end_time_update_cycle_no_tasks = self.hass.loop.time()
            if self._enable_debug_logging:
                _LOGGER.info(
                    f"COMPLETED _async_update_data cycle (no groups due) at {dt_util.as_local(dt_util.utcnow())}. "
                    f"Duration: {end_time_update_cycle_no_tasks - start_time_update_cycle:.2f}s"
                )
            return self.data

        # --- Sequentially fetch data for due groups ---
        _LOGGER.debug(
            f"Due groups to fetch sequentially: {[g[0] for g in due_groups_to_fetch_sequentially]}"
        )
        any_group_fetched_successfully_this_cycle = False

        # Iterate through due groups and fetch data one by one.
        for i, (group_key, payload_config) in enumerate(due_groups_to_fetch_sequentially):
            _LOGGER.debug(
                f"Fetching data for due group: {group_key} (Index {i} of {len(due_groups_to_fetch_sequentially)} due groups)"
            )
            try:
                success = await self._fetch_group_data(group_key, payload_config)
                if success:
                    # On successful fetch, update last poll time for this group
                    # and flag that at least one group succeeded this cycle.
                    self._last_update_times[group_key] = self.hass.loop.time()
                    any_group_fetched_successfully_this_cycle = True
            except HdgApiConnectionError as err:
                # If a connection error occurs for any group, log it and raise UpdateFailed.
                # This signals HA that the entire update cycle failed, likely retrying later.
                _LOGGER.warning(
                    f"Connection error for group {group_key} during sequential fetch: {err}"
                )
                raise UpdateFailed(f"Connection error for group {group_key}: {err}") from err
            # Note: HdgApiResponseError (and other non-connection errors) are handled
            # within _fetch_group_data, which returns False. The loop continues.

            # Delay if not the last group in this cycle's list of due groups.
            # This spreads API calls even within a single coordinator update run.
            if i < len(due_groups_to_fetch_sequentially) - 1:
                _LOGGER.debug(
                    f"Waiting {INITIAL_SEQUENTIAL_INTER_GROUP_DELAY_S}s before polling next due group."
                )
                await asyncio.sleep(INITIAL_SEQUENTIAL_INTER_GROUP_DELAY_S)

        if not any_group_fetched_successfully_this_cycle and due_groups_to_fetch_sequentially:
            # This occurs if groups were due, but none fetched successfully
            # (e.g., all had HdgApiResponseError or other non-connection errors).
            # Different from HdgApiConnectionError, which would have raised UpdateFailed earlier.
            _LOGGER.warning(
                "Attempted to poll due groups, but no group updated successfully in this cycle."  # pragma: no cover
            )

        # Log completion of the update cycle, including duration.
        end_time_update_cycle_with_tasks = self.hass.loop.time()
        if self._enable_debug_logging:
            _LOGGER.info(
                f"COMPLETED _async_update_data cycle (sequentially processed {len(due_groups_to_fetch_sequentially)} due groups) at {dt_util.as_local(dt_util.utcnow())}. "
                f"Duration: {end_time_update_cycle_with_tasks - start_time_update_cycle:.2f}s"
            )
        return self.data

    async def async_update_internal_node_state(self, node_id: str, new_value: Any) -> None:
        """
        Update a single node's value in internal data store and notify listeners.

        Typically called by `async_set_node_value_if_changed` after a successful
        API set operation to reflect the change immediately, avoiding wait for
        the next polling cycle.
        Args:
            node_id: Base HDG node ID (no suffix).
            new_value: New value for the node.
        """
        node_id_str = str(node_id).strip()
        # Ensure comparison is string-based, as API values are strings.
        current_value_str = str(new_value)

        # Only update and notify if the new value differs from the current stored value
        # to prevent unnecessary updates and event notifications.
        if self.data.get(node_id_str) != current_value_str:
            self.data[node_id_str] = current_value_str
            _LOGGER.debug(
                f"Internal state for node '{node_id_str}' updated to '{current_value_str}'. Notifying listeners."
            )
            self.async_set_updated_data(self.data)
        else:
            _LOGGER.debug(
                f"Internal state for node '{node_id_str}' already '{current_value_str}'. No update notification."
            )

    async def async_set_node_value_if_changed(
        self, node_id: str, new_value_to_set: Any, entity_name_for_log: str = "Unknown Entity"
    ) -> bool:
        """
        Set node value via API if different from current; updates internal state.

        Centralizes logic for setting values, including "if_changed" check.
        Used by number entities and services.
        Args:
            node_id: Base HDG node ID (no TUVWXY suffix).
            new_value_to_set: New value; converted to string for API.
            entity_name_for_log: Name of initiating entity/service for logging.

        Returns:
            True if value set via API or already matched.
            False if API call reported failure (non-critical).

        Raises:
            HdgApiError: On unrecoverable API client error during set operation.
        """
        node_id_str = str(node_id).strip()
        # Ensure value sent to API and for comparison is string.
        # HDG API expects string for set; stored data is also string.
        api_value_to_send_str = str(new_value_to_set)

        # Retrieve current known raw value from coordinator's data store.
        current_known_raw_value = self.data.get(node_id_str)

        # If current known value matches desired, no API call needed.
        if (
            current_known_raw_value is not None
            and str(current_known_raw_value) == api_value_to_send_str
        ):
            _LOGGER.info(
                f"Coordinator: Value for node '{entity_name_for_log}' (ID: {node_id_str}) is already '{api_value_to_send_str}'. Skipping API call."
            )
            return True

        # If value is different or not known, attempt to set it via API client.
        # `api_client.async_set_node_value` handles the HTTP request.
        success = await self.api_client.async_set_node_value(node_id_str, api_value_to_send_str)
        if success:
            _LOGGER.info(
                f"Coordinator: Successfully set node '{entity_name_for_log}' (ID: {node_id_str}) to '{api_value_to_send_str}' via API."
            )
            # Update internal state immediately to reflect the change.
            await self.async_update_internal_node_state(node_id_str, api_value_to_send_str)
            return True
        else:
            # `api_client.async_set_node_value` returned False. Typically means
            # API call made but failed (e.g., HTTP 200 not received),
            # but not a connection error (which would raise HdgApiConnectionError).
            _LOGGER.error(
                f"Coordinator: API call to set node '{entity_name_for_log}' (ID: {node_id_str}) to '{api_value_to_send_str}' reported failure."
            )
            return False
