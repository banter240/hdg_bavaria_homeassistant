"""
Manages data fetching and updates for the HDG Bavaria Boiler integration.

This module defines the `HdgDataUpdateCoordinator` class, which is central
to the HDG Bavaria Boiler integration. It handles polling data from the
boiler's API, managing different data groups with varying update intervals,
processing the received data, and coordinating requests to set values on the boiler.
The coordinator ensures that API interactions are managed efficiently, respecting
API rate limits and handling potential connection or response issues.
"""

__version__ = "0.10.22"

import asyncio
import logging
import time
from asyncio import Task
from contextlib import suppress
from datetime import timedelta
from typing import (
    Any,
)

import async_timeout
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.util import dt as dt_util

from .api import (
    HdgApiClient,
    HdgApiConnectionError,
    HdgApiError,
    HdgApiResponseError,
)
from .const import (
    CONF_ENABLE_DEBUG_LOGGING,
    DEFAULT_ENABLE_DEBUG_LOGGING,
    DOMAIN,
    INITIAL_SEQUENTIAL_INTER_GROUP_DELAY_S,
    POLLING_API_LOCK_TIMEOUT_S,
    RECENTLY_SET_POLL_IGNORE_WINDOW_S,
    SET_NODE_COOLDOWN_S,
    SET_VALUE_QUEUE_MAX_SIZE,
    SET_VALUE_RETRY_BASE_BACKOFF_S,
    SET_VALUE_RETRY_MAX_ATTEMPTS,
)
from .const import (
    MIN_SCAN_INTERVAL as CONFIG_FLOW_MIN_SCAN_INTERVAL,
)
from .polling_groups import (
    HDG_NODE_PAYLOADS,
    POLLING_GROUP_ORDER,
    NodeGroupPayload,
)
from .utils import strip_hdg_node_suffix

_LOGGER = logging.getLogger(DOMAIN)


class HdgDataUpdateCoordinator(DataUpdateCoordinator[dict[str, Any]]):
    """
    Manages fetching data from the HDG boiler and coordinates updates to entities.

    This class is responsible for polling the boiler API at configured intervals,
    processing the received data, and handling queued requests to set values on
    the boiler. It uses an `HdgApiClient` for communication and manages different
    polling groups with varying update frequencies. A background worker task handles
    setting values to the boiler, including retry logic.

    Key instance variables:
        hass (HomeAssistant): The Home Assistant instance.
        api_client (HdgApiClient): Client for API communication.
        entry (ConfigEntry): The configuration entry for this integration instance.
        scan_intervals (Dict[str, timedelta]): Scan intervals for each polling group.
        data (Dict[str, Any]): The central data store for polled values.
        _api_lock (asyncio.Lock): Lock to serialize API access (both polling and setting).
        _pending_set_values (Dict[str, tuple[str, str]]): Queue for pending set operations.
        _set_value_worker_task (Optional[asyncio.Task]): Task handle for the background set worker.
        _last_set_times (Dict[str, float]): Timestamps of last successful set operations per node.
    """

    def __init__(
        self,
        hass: HomeAssistant,
        api_client: HdgApiClient,
        entry: ConfigEntry,
    ):
        """
        Initialize the HdgDataUpdateCoordinator.

        Sets up scan intervals based on configuration, validates polling group
        definitions, initializes internal state for data management, API locking,
        and the set value worker.

        Args:
            hass: The Home Assistant instance.
            api_client: The `HdgApiClient` instance for API communication.
            entry: The `ConfigEntry` for this integration instance.

        Raises:
            ValueError: If there's a critical mismatch between `POLLING_GROUP_ORDER`
                        and `HDG_NODE_PAYLOADS` definitions.
        """
        self.hass = hass
        self.api_client = api_client
        self.entry = entry
        current_config = self.entry.options or self.entry.data
        self.scan_intervals: dict[str, timedelta] = {}

        # Validate that polling group definitions in polling_groups.py are consistent.
        # This is a critical check to ensure the coordinator can operate correctly.
        polling_group_set = set(POLLING_GROUP_ORDER)
        payloads_key_set = set(HDG_NODE_PAYLOADS.keys())
        if polling_group_set != payloads_key_set:
            missing_in_payloads = polling_group_set - payloads_key_set
            missing_in_order = payloads_key_set - polling_group_set
            error_msg = (
                "CRITICAL CONFIGURATION MISMATCH: POLLING_GROUP_ORDER and HDG_NODE_PAYLOADS keys do not match. "
                f"Missing in HDG_NODE_PAYLOADS: {missing_in_payloads or 'None'}. "
                f"Missing in POLLING_GROUP_ORDER: {missing_in_order or 'None'}. "
                "Please check polling_groups.py."
            )
            _LOGGER.error(error_msg)
            # Halt initialization if critical configuration is broken.
            if missing_in_payloads or missing_in_order:
                raise ValueError(error_msg)

        # Load and validate scan intervals for each polling group from the config entry.
        for group_key, payload_details in HDG_NODE_PAYLOADS.items():
            config_key_for_scan = payload_details["config_key_scan_interval"]
            default_scan_val = payload_details["default_scan_interval"]
            raw_scan_val = current_config.get(config_key_for_scan, default_scan_val)
            try:
                scan_val_seconds_float = float(raw_scan_val)
                if scan_val_seconds_float < CONFIG_FLOW_MIN_SCAN_INTERVAL:
                    _LOGGER.warning(
                        f"Scan interval {scan_val_seconds_float}s for group '{group_key}' is below minimum {CONFIG_FLOW_MIN_SCAN_INTERVAL}s. "
                        f"Using default: {default_scan_val}s."
                    )
                    scan_val_seconds_float = float(default_scan_val)
            except (ValueError, TypeError):
                _LOGGER.warning(
                    f"Invalid scan interval '{raw_scan_val}' for group '{group_key}'. Using default: {default_scan_val}s."
                )
                scan_val_seconds_float = float(default_scan_val)
            self.scan_intervals[group_key] = timedelta(seconds=scan_val_seconds_float)

        self._last_update_times: dict[str, float] = {}
        self._initialize_last_update_times_monotonic()  # Set initial last update times for all groups.

        # Determine the shortest scan interval to use as the base update interval for the coordinator.
        shortest_interval = (
            min(self.scan_intervals.values())
            if self.scan_intervals
            else timedelta(seconds=60)
        )

        super().__init__(
            hass,
            _LOGGER,
            name=f"{DOMAIN} ({self.entry.title})",
            update_interval=shortest_interval,  # This interval triggers _async_update_data.
        )
        self.data: dict[str, Any] = {}  # Central data store for all node values.
        self._api_lock = asyncio.Lock()  # Ensures sequential access to the HDG API.
        self._pending_set_values: dict[
            str, tuple[str, str]
        ] = {}  # Queue for set operations.
        self._pending_set_values_lock = (
            asyncio.Lock()
        )  # Lock for accessing _pending_set_values.
        self._new_set_value_event = (
            asyncio.Event()
        )  # Signals the set worker of new items.
        self._last_set_times: dict[str, float] = {}
        self._set_value_worker_task: Task[None] | None = None
        # The set_value worker task is started in __init__.py after the coordinator
        # is successfully initialized and the initial data refresh is complete.
        self._set_value_worker_task = (
            None  # Initialized to None, assigned in __init__.py
        )

        _LOGGER.debug(
            f"HdgDataUpdateCoordinator for '{self.entry.title}' initialized. Update interval: {shortest_interval}."
        )

    @property
    def enable_debug_logging(self) -> bool:
        """Return True if detailed debug logging for polling cycles is enabled."""
        return bool(
            (self.entry.options or {}).get(
                CONF_ENABLE_DEBUG_LOGGING, DEFAULT_ENABLE_DEBUG_LOGGING
            )
        )

    @property
    def last_update_times_public(self) -> dict[str, float]:
        """Return the dictionary of last update times for polling groups."""
        return self._last_update_times

    def _initialize_last_update_times_monotonic(self) -> None:
        """
        Set initial 'last update time' for all polling groups to 0.0.

        This ensures that all groups are polled during the first update cycle
        after initialization or reload.
        """
        for group_key in POLLING_GROUP_ORDER:  # Ensures consistent processing order.
            if group_key in self.scan_intervals:
                self._last_update_times[group_key] = 0.0
            else:  # Should be caught by __init__ validation
                _LOGGER.warning(
                    f"Polling group '{group_key}' from POLLING_GROUP_ORDER not in scan_intervals. Skipping init."
                )

    def _log_fetch_error_duration(
        self, group_key: str, error_type: str, start_time: float, error: Exception
    ) -> None:
        """
        Log error details and duration of a failed fetch attempt.

        This is a helper for logging errors encountered during API polling,
        conditionally active if debug logging is enabled.

        Args:
            group_key: The key of the polling group that failed.
            error_type: A string describing the type of error (e.g., "Connection error").
            start_time: The monotonic time when the fetch attempt started.
            error: The exception that occurred.
        """
        if self.enable_debug_logging:
            duration = time.monotonic() - start_time
            _LOGGER.warning(
                f"{error_type.upper()} for group: {group_key} at {dt_util.as_local(dt_util.utcnow())}. "
                f"Duration: {duration:.2f}s. Error: {error}"
            )

    def _validate_and_extract_api_item_fields(
        self, item: dict[str, Any], group_key: str
    ) -> tuple[str | None, str | None]:
        """
        Validate and extract 'id' and 'text' fields from a single API item dictionary.

        Ensures that the item is a dictionary and contains non-empty 'id' and 'text'
        fields of the expected types (string or int for 'id', string for 'text').
        The 'id' is the raw node ID from the API (often with a suffix like 'T').
        The 'text' is the raw string value of the node.

        Args:
            item: The dictionary representing a single data point from the API response.
            group_key: The key of the polling group this item belongs to, for logging context.

        Returns:
            A tuple containing the validated node ID (as a string) and the item text value
            (as a string), or (None, None) if validation fails for critical fields.
            If 'text' is missing but 'id' is valid, returns (node_id_with_suffix, None).
        """
        api_id_value = item.get("id")
        node_id_with_suffix: str | None = None

        # Validate 'id' field
        if isinstance(api_id_value, str):
            node_id_with_suffix = api_id_value.strip()
            if not node_id_with_suffix:
                _LOGGER.warning(
                    f"API item in group '{group_key}' has empty 'id'. Item: {item}. Skipping."
                )
                return None, None
        elif isinstance(api_id_value, int):
            node_id_with_suffix = str(api_id_value)
        else:
            _LOGGER.warning(
                f"API item in group '{group_key}' has invalid 'id' type. Item: {item}. Skipping."
            )
            return None, None

        # Validate 'text' field
        item_text_value = item.get("text")
        if item_text_value is None:
            _LOGGER.warning(
                f"API item for node '{node_id_with_suffix}' in group '{group_key}' missing 'text'. Item: {item}. Skipping."
            )
            return (
                node_id_with_suffix,
                None,
            )  # Return ID even if text is missing, for potential partial data handling.

        # Ensure item_text_value is a string, as expected by consumers.
        # The API typically sends strings, but this adds robustness.
        if not isinstance(item_text_value, str):
            _LOGGER.debug(
                f"API item text for node '{node_id_with_suffix}' is not a string ({type(item_text_value)}), converting. Value: {item_text_value}"
            )
            item_text_value = str(item_text_value)

        return node_id_with_suffix, item_text_value

    def _should_ignore_polled_item(
        self, node_id_clean: str, item_text_value: str, group_key_for_log: str
    ) -> bool:
        """
        Determine if a polled API item should be ignored due to a recent set operation.

        This prevents a stale value from a poll response from overwriting a value
        that was just successfully set via an API call. It checks if the node
        was set recently (within `RECENTLY_SET_POLL_IGNORE_WINDOW_S`) and if the
        polled value is different from the value currently held in the coordinator's
        data store (which should reflect the recently set value).

        Args:
            node_id_clean: The cleaned base node ID (without T/U/V/W/X/Y suffix).
            item_text_value: The text value of the item from the API response.
            group_key_for_log: The polling group key, for logging context.

        Returns:
            True if the item should be ignored, False otherwise.
        """
        last_set_time_for_node = self._last_set_times.get(node_id_clean, 0.0)
        current_time_monotonic = (
            time.monotonic()
        )  # Use current time for accurate window comparison.

        was_recently_set = (
            last_set_time_for_node > 0.0  # Check if it was ever set.
            and (current_time_monotonic - last_set_time_for_node)
            < RECENTLY_SET_POLL_IGNORE_WINDOW_S  # Check if within the ignore window.
        )

        if was_recently_set:
            current_coordinator_value = self.data.get(node_id_clean)
            # If the polled value differs from what the coordinator thinks it should be (after a set), ignore the poll.
            if current_coordinator_value != item_text_value:
                _LOGGER.debug(
                    f"Ignoring polled value '{item_text_value}' for node '{node_id_clean}' (group '{group_key_for_log}'). "
                    f"Node was recently set via API (at {last_set_time_for_node:.2f}, "
                    f"current time {current_time_monotonic:.2f}, "
                    f"window: {RECENTLY_SET_POLL_IGNORE_WINDOW_S}s). "
                    f"Coordinator currently holds '{current_coordinator_value}'. Polled value ignored."
                )
                return True  # Ignore this polled item
            else:
                # If values match, it's safe to process the polled value, even if recently set.
                _LOGGER.debug(
                    f"Polled value '{item_text_value}' for node '{node_id_clean}' matches coordinator value '{current_coordinator_value}'. "
                    f"Node was recently set, but values match. Proceeding with polled value."
                )
                return False  # Do not ignore, values match
        elif self.enable_debug_logging:  # Log only if not recently set and debug is on.
            _LOGGER.debug(
                f"Processing polled value '{item_text_value}' for node '{node_id_clean}'. "
                f"Not recently set OR ignore window passed (last_set: {last_set_time_for_node:.2f}, current_time: {current_time_monotonic:.2f}, window: {RECENTLY_SET_POLL_IGNORE_WINDOW_S}s)."
            )
        return False  # Not recently set or window passed, do not ignore

    def _process_single_api_item(
        self,
        item: dict[str, Any],
        group_key: str,
        raw_ids_seen: set[str],
        cleaned_node_ids_processed: set[str],
    ) -> dict[str, Any] | None:
        """
        Process a single item from the API response list.

        Validates the item's structure, checks for duplicate raw and cleaned node IDs
        within the current API response batch, and applies the "recently set" ignore logic.
        If the item is valid and should not be ignored, its cleaned value is stored
        in `self.data`.

        Args:
            item: The dictionary representing a single data point from the API response.
            group_key: The key of the polling group this item belongs to, for logging context.
            raw_ids_seen: A set tracking raw node IDs encountered in the current API response batch
                          to detect duplicates from the API itself.
            cleaned_node_ids_processed: A set tracking cleaned node IDs processed in the current
                                        API response batch to detect duplicates after suffix stripping.

        Returns:
            The original item dictionary if it was successfully processed and stored,
            or None if it was skipped due to validation errors, duplicates, or the
            "recently set" ignore logic.
        """
        # Step 1: Basic validation of 'id' and 'text' fields.
        node_id_with_suffix, item_text_value = (
            self._validate_and_extract_api_item_fields(item, group_key)
        )
        if node_id_with_suffix is None or item_text_value is None:
            return None  # Critical fields missing or invalid.

        # Step 2: Check for duplicate raw node IDs within the same API call.
        # This catches issues if the API itself sends the same raw ID multiple times.
        if node_id_with_suffix in raw_ids_seen:
            _LOGGER.error(
                f"Duplicate raw node ID '{node_id_with_suffix}' in API response for group '{group_key}'. Item: {item}. Skipping."
            )
            return None
        raw_ids_seen.add(node_id_with_suffix)

        # Step 3: Clean the node ID (remove suffix) and apply "recently set" logic.
        node_id_clean = strip_hdg_node_suffix(node_id_with_suffix)
        if self._should_ignore_polled_item(node_id_clean, item_text_value, group_key):
            return None  # Item was recently set and polled value is stale.

        # Step 4: Check for duplicate cleaned node IDs.
        # This catches cases like "123T" and "123U" both mapping to "123".
        if node_id_clean in cleaned_node_ids_processed:
            existing_value = self.data.get(node_id_clean)
            log_level = (
                _LOGGER.critical if existing_value != item_text_value else _LOGGER.debug
            )
            log_level(
                f"Duplicate base node ID '{node_id_clean}' (from API ID '{node_id_with_suffix}') "
                f"in API response for group '{group_key}' "
                f"{'WITH CONFLICTING VALUES' if existing_value != item_text_value else 'with identical value'}. "
                f"Existing: '{existing_value}', New (skipped): '{item_text_value}'."
            )
            return None

        # Step 5: Store the valid, non-ignored, unique item in the coordinator's data.
        self.data[node_id_clean] = item_text_value
        cleaned_node_ids_processed.add(node_id_clean)
        return item  # Return the original item to indicate successful processing.

    def _parse_and_store_api_items(
        self,
        group_key: str,
        api_items: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        """
        Parse, validate, and store API items from a polling group response.

        This method iterates through each item received from the API for a specific
        polling group. For each item, it delegates processing to
        `_process_single_api_item`, which handles validation, duplicate checks,
        and the "recently set" logic. Only successfully processed items are
        collected and returned.

        Args:
            group_key: The key of the polling group these items belong to.
            api_items: A list of dictionaries, where each dictionary is an item
                       from the API response (e.g., `[{'id': '123T', 'text': 'value'}]`).

        Returns:
            A list containing the original dictionaries of API items that were
            successfully processed and whose data was stored in `self.data`.
            Items that were skipped or ignored are not included.
        """
        successfully_processed_items: list[dict[str, Any]] = []
        raw_ids_seen_in_this_call: set[str] = (
            set()
        )  # Tracks raw IDs within this single API response.
        cleaned_node_ids_processed_this_call: set[str] = (
            set()
        )  # Tracks cleaned IDs within this response.

        for item in api_items:
            # Delegate processing of each item.
            if processed_item := self._process_single_api_item(
                item,
                group_key,
                raw_ids_seen_in_this_call,
                cleaned_node_ids_processed_this_call,
            ):
                successfully_processed_items.append(processed_item)
        return successfully_processed_items

    async def _fetch_group_data(
        self,
        group_key: str,
        payload_config: NodeGroupPayload,
        polling_cycle_start_time_for_log: float,
    ) -> list[dict[str, Any]] | None:
        """
        Fetch and process data for a single polling group.

        Acquires the API lock, makes the API call using `self.api_client`,
        and then processes the response using `_parse_and_store_api_items`.
        Handles various API-related exceptions and logs fetch duration if
        debug logging is enabled.

        Args:
            group_key: The key of the polling group to fetch (e.g., "group1_realtime_core").
            payload_config: The configuration dictionary for this group from `HDG_NODE_PAYLOADS`.
            polling_cycle_start_time_for_log: The monotonic time when the overall
                                              polling cycle started, used for logging duration context.

        Returns:
            A list of successfully processed API item dictionaries if the fetch and
            parse were successful. Returns `None` if the API call itself returned no data
            without an error, or if an `HdgApiResponseError` or `asyncio.TimeoutError`
            occurred during the lock acquisition or API call.

        Raises:
            HdgApiConnectionError: If a connection-level error occurs during the API call.
            Exception: For other unexpected errors during the fetch process.
        """
        payload_str = payload_config.get("payload_str")
        if (
            payload_str is None
        ):  # Should be caught by __init__ validation, but safeguard here.
            _LOGGER.error(
                f"Config error: 'payload_str' missing for group '{group_key}'."
            )
            return None
        try:
            # Acquire lock to ensure exclusive API access for this fetch operation.
            async with async_timeout.timeout(POLLING_API_LOCK_TIMEOUT_S):
                async with self._api_lock:
                    start_time_group_fetch_actual = time.monotonic()
                    if self.enable_debug_logging:
                        _LOGGER.info(
                            f"FETCHING (lock acquired) for group: {group_key} at {dt_util.as_local(dt_util.utcnow())}"
                        )
                    # Perform the API call.
                    fetched_data_list = await self.api_client.async_get_nodes_data(
                        payload_str
                    )
            # Lock is released automatically here.

            if fetched_data_list is not None:
                # Parse and store the fetched data.
                processed_items = self._parse_and_store_api_items(
                    group_key, fetched_data_list
                )
                _LOGGER.debug(
                    f"Processed data for HDG group: {group_key}. {len(processed_items)} valid items."
                )
                if self.enable_debug_logging:
                    duration_fetch_actual = (
                        time.monotonic() - start_time_group_fetch_actual
                    )
                    _LOGGER.info(
                        f"COMPLETED FETCH for group: {group_key}. Duration: {duration_fetch_actual:.2f}s"
                    )
                return processed_items  # Return the list of items that were successfully processed.
            _LOGGER.warning(
                f"Polling for group {group_key} returned None from api_client without error."
            )
            return None
        except HdgApiConnectionError as conn_err:  # Network or connection issue.
            self._log_fetch_error_duration(
                group_key,
                "Connection error",
                polling_cycle_start_time_for_log,
                conn_err,
            )
            raise  # Re-raise to be handled by the calling method (_sequentially_fetch_groups).
        except (
            HdgApiResponseError
        ) as err:  # API returned an error or unexpected response.
            self._log_fetch_error_duration(
                group_key, "API response error", polling_cycle_start_time_for_log, err
            )
            return None  # Treat as a failed fetch for this group, but don't stop overall polling.
        except TimeoutError:  # Timeout waiting for the API lock.
            _LOGGER.warning(
                f"Polling for group {group_key} timed out after {POLLING_API_LOCK_TIMEOUT_S}s waiting for API lock."
            )
            return None
        except Exception as err:  # Catch any other unexpected errors.
            _LOGGER.exception(f"Unexpected error polling group '{group_key}': {err}")
            raise  # Re-raise to ensure it's not silently ignored.

    async def _sequentially_fetch_groups(
        self,
        groups_to_fetch: list[tuple[str, NodeGroupPayload]],
        polling_cycle_start_time: float,
    ) -> tuple[bool, bool]:
        """
        Fetch data for multiple polling groups sequentially.

        Iterates through the provided list of groups, fetching data for each
        using `_fetch_group_data`. A short delay (`INITIAL_SEQUENTIAL_INTER_GROUP_DELAY_S`)
        is introduced between fetching different groups to avoid overwhelming the API.
        This method tracks whether any group was successfully fetched and if any
        connection errors were encountered during the process.

        Args:
            groups_to_fetch: A list of tuples, where each tuple contains
                             (group_key, payload_config) for a polling group.
            polling_cycle_start_time: The monotonic time when the overall polling cycle
                                      started, used for logging context in `_fetch_group_data`.

        Returns:
            A tuple containing:
            - bool: True if at least one group was fetched successfully, False otherwise.
            - bool: True if at least one `HdgApiConnectionError` was encountered
                    during the fetching of any group, False otherwise.
        """
        any_group_fetched_successfully = False
        any_connection_error_encountered = False

        for i, (group_key, payload_config) in enumerate(groups_to_fetch):
            _LOGGER.debug(
                f"Fetching data for group: {group_key} (Index {i + 1}/{len(groups_to_fetch)})"
            )
            try:
                processed_items = await self._fetch_group_data(
                    group_key, payload_config, polling_cycle_start_time
                )
                if (
                    processed_items is not None
                ):  # Indicates successful fetch and parse for this group.
                    self._last_update_times[group_key] = time.monotonic()
                    any_group_fetched_successfully = True
            except (
                HdgApiConnectionError
            ) as err:  # Connection error specific to this group.
                _LOGGER.warning(
                    f"Connection error for group {group_key} during sequential fetch: {err}."
                )
                any_connection_error_encountered = True
            # Introduce a delay before fetching the next group, if any.
            if i < len(groups_to_fetch) - 1:
                _LOGGER.debug(
                    f"Waiting {INITIAL_SEQUENTIAL_INTER_GROUP_DELAY_S}s before next group."
                )
                await asyncio.sleep(INITIAL_SEQUENTIAL_INTER_GROUP_DELAY_S)
        return any_group_fetched_successfully, any_connection_error_encountered

    async def async_config_entry_first_refresh(self) -> None:
        """
        Perform initial sequential data refresh for all polling groups.

        This method is called once during the setup of the integration (specifically
        in `async_setup_entry` in `__init__.py`). It fetches data for all defined
        polling groups in the order specified by `POLLING_GROUP_ORDER` to populate
        the initial state of the entities. If this initial refresh fails to retrieve
        any data from any group, it raises `UpdateFailed` to signal Home Assistant
        that the setup cannot proceed.

        Raises:
            UpdateFailed: If no data could be retrieved from any polling group
                          during the initial refresh.
        """
        start_time_first_refresh = time.monotonic()
        if self.enable_debug_logging:
            _LOGGER.info(
                f"INITIATING async_config_entry_first_refresh for {self.name} at {dt_util.as_local(dt_util.utcnow())} "
                f"with {INITIAL_SEQUENTIAL_INTER_GROUP_DELAY_S}s inter-group delay."
            )

        # Prepare a list of all groups to fetch, respecting POLLING_GROUP_ORDER.
        all_groups_to_fetch = [
            (gk, HDG_NODE_PAYLOADS[gk])
            for gk in POLLING_GROUP_ORDER
            if gk in HDG_NODE_PAYLOADS
        ]

        # Attempt to fetch data for all groups.
        (
            any_group_fetched_successfully,
            any_connection_error_encountered,
        ) = await self._sequentially_fetch_groups(
            all_groups_to_fetch, start_time_first_refresh
        )

        # Check if the initial refresh was successful.
        if not any_group_fetched_successfully:
            error_message = (
                f"Initial data refresh for {self.name} failed to retrieve any data."
            )
            if any_connection_error_encountered:
                error_message += " Connection errors encountered."
            else:
                error_message += (
                    " No connection errors, but all groups failed to yield data."
                )
            _LOGGER.error(error_message)
            raise UpdateFailed(error_message)  # Signal HA that setup failed.
        elif (
            not self.data
        ):  # Successfully fetched some groups, but self.data is still empty.
            _LOGGER.warning(
                f"Initial data refresh for {self.name} completed, but no data was fetched overall."
            )

        if self.enable_debug_logging:
            duration = time.monotonic() - start_time_first_refresh
            _LOGGER.info(
                f"COMPLETED async_config_entry_first_refresh for {self.name}. Duration: {duration:.2f}s. "
                f"Items: {len(self.data or [])}"
            )
        # Notify Home Assistant and entities about the updated data.
        self.async_set_updated_data(self.data)

    def _get_due_polling_groups(
        self, current_time_monotonic: float
    ) -> list[tuple[str, NodeGroupPayload]]:
        """
        Identify polling groups that are due for an update based on their scan intervals.

        Compares the current monotonic time against the last update time for each group
        and its configured scan interval. Groups are returned in the order defined
        by `POLLING_GROUP_ORDER`.

        Args:
            current_time_monotonic: The current time from `time.monotonic()`.

        Returns:
            A list of tuples, where each tuple contains (group_key, payload_config)
            for a polling group that is due for an update.
        """
        due_groups: list[tuple[str, NodeGroupPayload]] = []
        for group_key in POLLING_GROUP_ORDER:  # Process in defined order.
            payload_config = HDG_NODE_PAYLOADS.get(group_key)
            # Ensure group is defined and has a scan interval.
            if not payload_config or group_key not in self.scan_intervals:
                _LOGGER.debug(
                    f"Skipping group '{group_key}' in due check: not defined or no scan_interval."
                )
                continue

            interval_seconds = self.scan_intervals[group_key].total_seconds()
            last_update = self._last_update_times.get(
                group_key, 0.0
            )  # Default to 0.0 if never updated.

            # Check if the time since last update exceeds the interval.
            if (current_time_monotonic - last_update) >= interval_seconds:
                due_groups.append((group_key, payload_config))
            elif self.enable_debug_logging:  # Log if not due and debug is enabled.
                next_poll_in = max(
                    0, interval_seconds - (current_time_monotonic - last_update)
                )
                _LOGGER.debug(
                    f"Skipping poll for HDG group: {group_key} (Next in approx. {next_poll_in:.0f}s)"
                )
        return due_groups

    async def _async_update_data(self) -> dict[str, Any]:
        """
        Fetch data for all polling groups that are currently due for an update.

        This is the main data update method called by the Home Assistant
        DataUpdateCoordinator's scheduling mechanism (based on `update_interval`
        set during `__init__`). It identifies which polling groups need updating
        based on their individual scan intervals (using `_get_due_polling_groups`)
        and then fetches their data sequentially (using `_sequentially_fetch_groups`).

        Returns:
            The updated data dictionary (`self.data`) which entities will use to
            refresh their states.

        Raises:
            UpdateFailed: If fetching data for all due groups fails due to
                          connection errors, signaling Home Assistant that the
                          update cycle was unsuccessful.
        """
        polling_cycle_start_time = time.monotonic()
        if self.enable_debug_logging:
            _LOGGER.info(
                f"INITIATING _async_update_data cycle at {dt_util.as_local(dt_util.utcnow())}"
            )

        # Determine which groups are due for an update.
        due_groups_to_fetch = self._get_due_polling_groups(polling_cycle_start_time)
        if not due_groups_to_fetch:
            _LOGGER.debug("No polling groups due for update in this cycle.")
            if self.enable_debug_logging:
                _LOGGER.info(
                    f"COMPLETED _async_update_data (no groups due). Duration: {time.monotonic() - polling_cycle_start_time:.3f}s"
                )
            return self.data  # Return current data if no groups are due.

        _LOGGER.debug(
            f"Due groups to fetch in this cycle: {[g[0] for g in due_groups_to_fetch]}"
        )

        # Fetch data for the due groups.
        (
            any_group_fetched_successfully,
            any_connection_error_encountered,
        ) = await self._sequentially_fetch_groups(
            due_groups_to_fetch, polling_cycle_start_time
        )

        # Handle cases where fetching failed for all due groups.
        if not any_group_fetched_successfully and due_groups_to_fetch:
            msg = "Failed to fetch data from HDG boiler for all due groups."
            if any_connection_error_encountered:
                msg += " Connection errors encountered."
                _LOGGER.error(msg)
                raise UpdateFailed(msg)  # Critical failure for this update cycle.
            # If no connection errors, but still no success, it implies API errors or other issues.
            _LOGGER.warning(f"{msg} API errors or other issues. Data may be stale.")

        if self.enable_debug_logging:
            _LOGGER.info(
                f"COMPLETED _async_update_data (processed {len(due_groups_to_fetch)} groups). Duration: {time.monotonic() - polling_cycle_start_time:.3f}s"
            )
        return self.data  # Return the (potentially updated) data.

    async def async_update_internal_node_state(
        self, node_id: str, new_value: str
    ) -> None:
        """
        Update a node's value in the internal data store and notify listeners.

        This method is called by the `_set_value_worker` after a value has been
        successfully set on the boiler via the API. It updates the coordinator's
        internal data cache (`self.data`) and triggers a Home Assistant state update
        for all entities using this coordinator. It also records the time the value
        was set (`_last_set_times`) to help `_should_ignore_polled_item` prevent
        subsequent polls from overwriting this fresh value with potentially stale data.

        Args:
            node_id: The base HDG node ID (without suffix, e.g., "6022").
            new_value: The new value as a string, exactly as it was successfully
                       sent to the API (and as it should be stored internally).
        """
        if self.data.get(node_id) != new_value:
            # Record the time of this successful set operation.
            self._last_set_times[node_id] = time.monotonic()
            # Update the internal data store.
            self.data[node_id] = new_value
            _LOGGER.debug(
                f"Internal state for node '{node_id}' updated to '{new_value}'. Notifying listeners."
            )
            # Notify Home Assistant and all subscribed entities of the data change.
            self.async_set_updated_data(self.data)
        else:
            _LOGGER.debug(
                f"Internal state for node '{node_id}' already '{new_value}'. No update needed."
            )

    def _calculate_set_worker_wait_timeout(
        self, retry_state: dict[str, tuple[int, float]]
    ) -> float | None:
        """
        Calculate the wait timeout for the `_set_value_worker`.

        Determines how long the worker should wait before its next processing cycle.
        This is primarily based on the earliest scheduled retry time for any pending
        set operations. If no retries are scheduled (i.e., `retry_state` is empty
        or contains no valid future attempt times), it returns `None`, causing the
        worker to wait indefinitely for the `_new_set_value_event`.

        Args:
            retry_state: A dictionary mapping node IDs to `(retry_count, next_attempt_monotonic_time)`.

        Returns:
            The timeout duration in seconds (float), or `None` to wait indefinitely.
            Returns 0 if a retry is immediately due.
        """
        if not retry_state:  # No items currently in retry state.
            return None

        # Collect all valid 'next_attempt_monotonic_time' values.
        if not (
            valid_retry_times := [
                next_attempt
                for _, next_attempt in retry_state.values()
                if isinstance(
                    next_attempt, int | float
                )  # Ensure it's a numeric timestamp.
            ]
        ):
            return None  # No valid retry times found.

        earliest_retry_time = min(valid_retry_times)
        # Calculate wait duration; ensure it's not negative.
        return max(0, earliest_retry_time - time.monotonic())

    async def _collect_items_to_process_for_set_worker(
        self, retry_state: dict[str, tuple[int, float]]
    ) -> dict[str, tuple[str, str]]:
        """
        Collect items for the `_set_value_worker` to process in the current cycle.

        Gathers items from `self._pending_set_values` that are either newly queued
        (retry_count is 0) or are due for a retry (current time is past their
        `next_attempt_time` as stored in `retry_state`). Items collected
        for processing are removed from `self._pending_set_values`; they will be
        re-added to `_pending_set_values` by `_handle_failed_set_operation` if a
        subsequent retry is scheduled.

        Args:
            retry_state: A dictionary mapping node IDs to `(retry_count, next_attempt_monotonic_time)`.

        Returns:
            A dictionary of items to process now, mapping `node_id` to
            `(value_str_for_api, entity_name_for_log)`.
        """
        items_to_process_now: dict[str, tuple[str, str]] = {}
        current_monotonic_time = time.monotonic()

        async with (
            self._pending_set_values_lock
        ):  # Ensure thread-safe access to the queue.
            # Iterate over a copy of items in case of modification during iteration.
            for node_id, data_tuple in list(self._pending_set_values.items()):
                retry_count, next_attempt_time = retry_state.get(node_id, (0, 0.0))
                # Process if it's a new item (retry_count == 0) or if its retry time is due.
                if retry_count == 0 or current_monotonic_time >= next_attempt_time:
                    items_to_process_now[node_id] = data_tuple
                    # Remove from pending queue; will be re-added if retry is needed.
                    self._pending_set_values.pop(node_id, None)
        return items_to_process_now

    async def _handle_successful_set_operation(
        self,
        node_id: str,
        value_str: str,
        entity_name: str,
        retry_state: dict[str, tuple[int, float]],
    ) -> None:
        """
        Handle successful API set operation.

        Logs the success, updates the internal coordinator state via
        `async_update_internal_node_state` (which also notifies HA entities),
        and removes the item from the `retry_state` dictionary as it no longer
        needs retrying.

        Args:
            node_id: The base HDG node ID that was set.
            value_str: The string value that was successfully set.
            entity_name: The name of the entity associated with this node, for logging.
            retry_state: The dictionary tracking retry attempts.
        """
        _LOGGER.info(
            f"Set_value_worker: Successfully set node '{entity_name}' (ID: {node_id}) to '{value_str}' via API."
        )
        # Update internal state and notify HA.
        await self.async_update_internal_node_state(node_id, value_str)
        # Remove from retry tracking as it's successful.
        retry_state.pop(node_id, None)

    async def _handle_failed_set_operation(
        self,
        node_id: str,
        value_str: str,
        entity_name: str,
        api_err: Exception,
        retry_state: dict[str, tuple[int, float]],
    ) -> None:
        """
        Handle a failed API set operation, including retry logic.

        Increments the retry count for the given `node_id`. If retries are
        exhausted (exceeds `SET_VALUE_RETRY_MAX_ATTEMPTS`), the item is logged
        as given up and removed from `retry_state`. Otherwise, it's rescheduled
        for a future attempt with an exponential backoff delay, re-added to
        `self._pending_set_values`, and the `_new_set_value_event` is set to
        ensure the worker re-evaluates its wait timeout.

        Args:
            node_id: The base HDG node ID that failed to set.
            value_str: The string value that was attempted.
            entity_name: The name of the entity, for logging.
            api_err: The exception that occurred during the API call.
            retry_state: The dictionary tracking retry attempts.
        """
        retry_count, _ = retry_state.get(node_id, (0, 0.0))  # Get current retry count.
        retry_count += 1

        if retry_count > SET_VALUE_RETRY_MAX_ATTEMPTS:
            _LOGGER.error(
                f"Set_value_worker: Node '{entity_name}' (ID: {node_id}) failed after {SET_VALUE_RETRY_MAX_ATTEMPTS} retries: {api_err}. Giving up."
            )
            retry_state.pop(node_id, None)  # Remove from retry tracking.
        else:
            # Calculate exponential backoff delay.
            backoff_delay = SET_VALUE_RETRY_BASE_BACKOFF_S * (2 ** (retry_count - 1))
            next_attempt_time = time.monotonic() + backoff_delay
            # Update retry state with new count and next attempt time.
            retry_state[node_id] = (retry_count, next_attempt_time)
            # Re-add to the main pending queue for the worker to pick up later.
            async with self._pending_set_values_lock:
                self._pending_set_values[node_id] = (value_str, entity_name)
            _LOGGER.warning(
                f"Set_value_worker: Node '{entity_name}' (ID: {node_id}) failed (attempt {retry_count}/{SET_VALUE_RETRY_MAX_ATTEMPTS}): {api_err}. Retrying in {backoff_delay:.1f}s."
            )
            # Signal the worker to potentially adjust its wait time for this new retry.
            self._new_set_value_event.set()

    async def _set_value_worker(self) -> None:
        """
        Background worker task to process pending 'set value' requests.

        This task runs continuously in the background after being started during
        integration setup. It waits for new set requests (signaled by
        `_new_set_value_event`) or for scheduled retry times. When active, it
        collects items to process, then iterates through them, attempting to
        set each value on the HDG boiler via `self.api_client.async_set_node_value`.
        It respects the `_api_lock` to ensure sequential API access and applies a
        cooldown (`SET_NODE_COOLDOWN_S`) between successful set operations.
        Failed operations are handled by `_handle_failed_set_operation`, which
        implements retry logic. The task continues until it is cancelled (e.g.,
        during integration unload).
        """
        _LOGGER.info("HDG set_value_worker started.")
        # {node_id: (retry_count, next_attempt_monotonic_time)}
        retry_state: dict[str, tuple[int, float]] = {}

        while True:  # Main loop of the worker.
            try:
                # Determine how long to wait: until the next retry or indefinitely for new items.
                wait_timeout = self._calculate_set_worker_wait_timeout(retry_state)
                # Wait for a new item event or until the timeout for a retry is reached.
                with suppress(
                    asyncio.TimeoutError
                ):  # Timeout is expected if waiting for a retry.
                    await asyncio.wait_for(
                        self._new_set_value_event.wait(), timeout=wait_timeout
                    )
                self._new_set_value_event.clear()  # Reset the event after waking.

                # Collect items that are new or due for retry.
                items_to_process_now = (
                    await self._collect_items_to_process_for_set_worker(retry_state)
                )
                if not items_to_process_now:  # No items to process, loop back to wait.
                    continue

                _LOGGER.debug(
                    f"Set_value_worker: Processing {len(items_to_process_now)} items."
                )

                # Process each item sequentially.
                for node_id, (value_str, entity_name) in items_to_process_now.items():
                    try:
                        # Acquire API lock before making the call.
                        async with self._api_lock:
                            _LOGGER.debug(
                                f"Set_value_worker: Acquired API lock for node '{entity_name}' (ID: {node_id})."
                            )
                            success = await self.api_client.async_set_node_value(
                                node_id, value_str
                            )
                        # API lock released here.

                        if (
                            not success
                        ):  # API call reported failure (e.g., HTTP non-200).
                            raise HdgApiError(
                                f"API reported failure for set_node_value on node {node_id}"
                            )

                        # Handle successful operation.
                        await self._handle_successful_set_operation(
                            node_id, value_str, entity_name, retry_state
                        )

                        # Apply cooldown after a successful API call.
                        _LOGGER.debug(
                            f"Set_value_worker: Cooling down for {SET_NODE_COOLDOWN_S}s after API call for node '{entity_name}' (ID: {node_id})."
                        )
                        await asyncio.sleep(SET_NODE_COOLDOWN_S)

                    except (
                        HdgApiConnectionError,
                        HdgApiError,
                        HdgApiResponseError,
                    ) as api_err:
                        # Handle API errors, including scheduling retries.
                        await self._handle_failed_set_operation(
                            node_id, value_str, entity_name, api_err, retry_state
                        )
                    except Exception as e:  # Catch-all for unexpected errors during single item processing.
                        _LOGGER.exception(
                            f"Set_value_worker: Unexpected error processing item for node '{entity_name}' (ID: {node_id}): {e}"
                        )
                        # Consider if this specific item should also be retried or dropped.
                        # For now, it's logged, and the worker continues with other items.

            except asyncio.CancelledError:  # Task was cancelled (e.g., during unload).
                _LOGGER.info("HDG set_value_worker cancelled.")
                break  # Exit the loop.
            except Exception as e:  # Catch-all for errors in the main worker loop.
                _LOGGER.exception(f"HDG set_value_worker main loop crashed: {e}")
                await asyncio.sleep(5)  # Prevent tight loop if crash is persistent.
        _LOGGER.info("HDG set_value_worker stopped.")

    async def async_set_node_value_if_changed(
        self,
        node_id: str,
        new_value_str_for_api: str,
        entity_name_for_log: str = "Unknown Entity",
    ) -> bool:
        """
        Queue a node value to be set on the boiler via the API.

        This method is called by entities (like `HdgBoilerNumber`) when a user
        requests a value change. It adds the request to an internal queue
        (`self._pending_set_values`) which is processed sequentially by the
        `_set_value_worker` background task. The request is only queued if the
        new value is different from the currently known value in the coordinator's
        data store (`self.data`). If the same `node_id` is already in the queue,
        its value is updated with `new_value_str_for_api`.

        Args:
            node_id: The base HDG node ID (without suffix, e.g., "6022") to set.
            new_value_str_for_api: The new value as a string, formatted as expected
                                   by the HDG API.
            entity_name_for_log: The name of the entity requesting the set, for
                                 logging context.

        Returns:
            True if the value was successfully queued (or if it already matched the
            current known value, thus skipping the queue).
            False if an unexpected error occurred while attempting to queue the value.

        Raises:
            TypeError: If `new_value_str_for_api` is not a string.
        """
        if not isinstance(new_value_str_for_api, str):
            _LOGGER.error(
                f"Invalid type for new_value_str_for_api: {type(new_value_str_for_api).__name__} for node '{entity_name_for_log}'. Expected str."
            )
            raise TypeError("new_value_str_for_api must be a string.")

        # Check if the value is already what the coordinator knows.
        current_known_raw_value = self.data.get(node_id)
        if (
            current_known_raw_value is not None
            and current_known_raw_value == new_value_str_for_api
        ):
            _LOGGER.info(
                f"Coordinator: Value for node '{entity_name_for_log}' (ID: {node_id}) is already '{new_value_str_for_api}'. Skipping API set."
            )
            return True  # No change needed.

        try:
            # Add or update the item in the pending queue.
            async with self._pending_set_values_lock:
                # Log if the queue is getting large, as it might indicate worker backlog.
                if (
                    node_id
                    not in self._pending_set_values  # Only log for new additions if queue is large.
                    and len(self._pending_set_values) >= SET_VALUE_QUEUE_MAX_SIZE
                ):
                    _LOGGER.warning(
                        "HDG pending set values dictionary is large (size=%d, max_warn=%d). Adding new request for node '%s'. Worker may be backlogged.",
                        len(self._pending_set_values),
                        SET_VALUE_QUEUE_MAX_SIZE,
                        node_id,
                    )
                # Add/update the request in the queue.
                self._pending_set_values[node_id] = (
                    new_value_str_for_api,
                    entity_name_for_log,
                )
            # Signal the worker that there's a new/updated item.
            self._new_set_value_event.set()
            _LOGGER.info(
                f"Updated pending set request for node '{entity_name_for_log}' (ID: {node_id}) with value '{new_value_str_for_api}'. Pending count: {len(self._pending_set_values)}"
            )
            return True
        except Exception as e:  # Catch any unexpected errors during queue management.
            _LOGGER.exception(
                f"Unexpected error updating pending set values for node '{entity_name_for_log}' (ID: {node_id}): {e}"
            )
            return False

    async def async_stop_set_value_worker(self) -> None:
        """
        Gracefully stop the background `_set_value_worker` task.

        This method is called during the integration unload process
        (e.g., when Home Assistant is shutting down or the config entry is removed).
        It cancels the worker task and waits for it to complete, ensuring that
        any ongoing operations are properly terminated.
        """
        if self._set_value_worker_task and not self._set_value_worker_task.done():
            _LOGGER.debug("Cancelling HDG set_value_worker task...")
            self._set_value_worker_task.cancel()  # Request cancellation.
            # Wait for the task to actually finish, with a timeout.
            with suppress(
                asyncio.TimeoutError, asyncio.CancelledError
            ):  # Handles both timeout and if task cancels itself quickly.
                await asyncio.wait_for(self._set_value_worker_task, timeout=10.0)
                _LOGGER.debug(
                    "HDG set_value_worker task successfully joined after cancellation."
                )
            self._set_value_worker_task = None  # Clear the task handle.
        else:
            _LOGGER.debug(
                "HDG set_value_worker task was not running or already stopped."
            )
