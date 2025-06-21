"""Processor for handling and parsing API responses for the HDG Bavaria Boiler.

This class encapsulates the logic for validating, transforming, and storing raw
API response data. It works in conjunction with the `HdgDataUpdateCoordinator`
to manage the state of boiler data nodes, including handling duplicate node IDs
and ignoring polled values that were recently set via API to prevent race conditions.
"""

from __future__ import annotations

__version__ = "0.1.1"

import logging
import time
from typing import TYPE_CHECKING, Any

from ..const import DOMAIN, RECENTLY_SET_POLL_IGNORE_WINDOW_S
from ..helpers.string_utils import strip_hdg_node_suffix

if TYPE_CHECKING:
    from ..coordinator import HdgDataUpdateCoordinator


_LOGGER = logging.getLogger(DOMAIN)


class HdgPollingResponseProcessor:
    """Processes raw API polling responses."""

    def __init__(self, coordinator: HdgDataUpdateCoordinator) -> None:
        """Initialize the HdgPollingResponseProcessor.

        Args:
            coordinator: The HdgDataUpdateCoordinator instance, used to access
                         shared data like `self.data` and `self._last_set_times`.

        """
        self._coordinator = coordinator
        _LOGGER.debug("HdgPollingResponseProcessor initialized.")

    def _validate_and_extract_api_item_fields(
        self, item: dict[str, Any], group_key: str
    ) -> tuple[str | None, str | None]:
        """Validate and extract 'id' and 'text' fields from a single API item dictionary."""
        api_id_value = item.get("id")
        node_id_with_suffix: str | None = None

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

        item_text_value = item.get("text")
        if item_text_value is None:
            _LOGGER.warning(
                f"API item for node '{node_id_with_suffix}' in group '{group_key}' missing 'text'. Item: {item}. Skipping."
            )
            return node_id_with_suffix, None

        if not isinstance(item_text_value, str):
            _LOGGER.debug(
                f"API item text for node '{node_id_with_suffix}' is not a string ({type(item_text_value)}), converting. Value: {item_text_value}"
            )
            item_text_value = str(item_text_value)

        return node_id_with_suffix, item_text_value

    def _should_ignore_polled_item(
        self, node_id_clean: str, item_text_value: str, group_key_for_log: str
    ) -> bool:
        """Determine if a polled API item should be ignored due to a recent set operation."""
        last_set_time_for_node = self._coordinator._last_set_times.get(
            node_id_clean, 0.0
        )
        current_time_monotonic = time.monotonic()

        was_recently_set = (
            last_set_time_for_node > 0.0
            and (current_time_monotonic - last_set_time_for_node)
            < RECENTLY_SET_POLL_IGNORE_WINDOW_S
        )

        if was_recently_set:
            current_coordinator_value = self._coordinator.data.get(node_id_clean)
            if current_coordinator_value != item_text_value:
                _LOGGER.debug(
                    f"Processor: Ignoring polled value '{item_text_value}' for node '{node_id_clean}' (group '{group_key_for_log}'). "
                    f"Node was recently set via API (at {last_set_time_for_node:.2f}, "
                    f"current time {current_time_monotonic:.2f}, "
                    f"window: {RECENTLY_SET_POLL_IGNORE_WINDOW_S}s). "
                    f"Coordinator currently holds '{current_coordinator_value}'. Polled value ignored."
                )
                return True
            _LOGGER.debug(
                f"Processor: Polled value '{item_text_value}' for node '{node_id_clean}' matches coordinator value '{current_coordinator_value}'. "
                f"Node was recently set, but values match. Proceeding with polled value."
            )
            return False
        if self._coordinator.enable_debug_logging:
            _LOGGER.debug(
                f"Processor: Processing polled value '{item_text_value}' for node '{node_id_clean}'. "
                f"Not recently set OR ignore window passed (last_set: {last_set_time_for_node:.2f}, current_time: {current_time_monotonic:.2f}, window: {RECENTLY_SET_POLL_IGNORE_WINDOW_S}s)."
            )
        return False

    def _process_single_api_item(
        self,
        item: dict[str, Any],
        group_key: str,
        raw_ids_seen: set[str],
        cleaned_node_ids_processed: set[str],
    ) -> dict[str, Any] | None:
        """Process a single item from the API response list."""
        node_id_with_suffix, item_text_value = (
            self._validate_and_extract_api_item_fields(item, group_key)
        )
        if node_id_with_suffix is None or item_text_value is None:
            return None

        if node_id_with_suffix in raw_ids_seen:
            _LOGGER.error(
                f"Processor: Duplicate raw node ID '{node_id_with_suffix}' in API response for group '{group_key}'. Item: {item}. Skipping."
            )
            return None
        raw_ids_seen.add(node_id_with_suffix)

        node_id_clean = strip_hdg_node_suffix(node_id_with_suffix)
        if self._should_ignore_polled_item(node_id_clean, item_text_value, group_key):
            return None

        if node_id_clean in cleaned_node_ids_processed:
            existing_value = self._coordinator.data.get(node_id_clean)
            log_level = (
                _LOGGER.critical if existing_value != item_text_value else _LOGGER.debug
            )
            log_level(
                f"Processor: Duplicate base node ID '{node_id_clean}' (from API ID '{node_id_with_suffix}') "
                f"in API response for group '{group_key}' "
                f"{'WITH CONFLICTING VALUES' if existing_value != item_text_value else 'with identical value'}. "
                f"Existing: '{existing_value}', New (skipped): '{item_text_value}'."
            )
            return None

        # IMPORTANT: This method now updates the coordinator's data directly.
        self._coordinator.data[node_id_clean] = item_text_value
        cleaned_node_ids_processed.add(node_id_clean)
        return item

    def parse_and_store_api_items(
        self,
        group_key: str,
        api_items: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        """Parse, validate, and store API items from a polling group response."""
        successfully_processed_items: list[dict[str, Any]] = []
        raw_ids_seen_in_this_call: set[str] = set()
        cleaned_node_ids_processed_this_call: set[str] = set()

        for item in api_items:
            if processed_item := self._process_single_api_item(
                item,
                group_key,
                raw_ids_seen_in_this_call,
                cleaned_node_ids_processed_this_call,
            ):
                successfully_processed_items.append(processed_item)
        return successfully_processed_items
