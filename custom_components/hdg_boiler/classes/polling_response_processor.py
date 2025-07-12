"""Processor for handling and parsing API responses for the HDG Bavaria Boiler.

This class encapsulates the logic for validating, transforming, and storing raw
API response data. It works in conjunction with the `HdgDataUpdateCoordinator`
to manage the state of boiler data nodes, including handling duplicate node IDs
and ignoring polled values that were recently set via API to prevent race conditions.
"""

from __future__ import annotations

__version__ = "0.2.0"

import logging
import time
from typing import TYPE_CHECKING, Any, cast

from ..const import (
    CONF_RECENTLY_SET_POLL_IGNORE_WINDOW_S,
    DEFAULT_RECENTLY_SET_POLL_IGNORE_WINDOW_S,
    PROCESSOR_LOGGER_NAME,
    DOMAIN,
)
from ..helpers.string_utils import strip_hdg_node_suffix
from ..helpers.logging_utils import format_for_log
from ..helpers.parsers import parse_sensor_value

if TYPE_CHECKING:
    from ..coordinator import HdgDataUpdateCoordinator


_PROCESSOR_LOGGER = logging.getLogger(PROCESSOR_LOGGER_NAME)
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
        _PROCESSOR_LOGGER.debug("HdgPollingResponseProcessor initialized.")

    def _validate_and_extract_api_item_fields(
        self, item: dict[str, Any], group_key: str
    ) -> tuple[str, str] | tuple[str, None] | tuple[None, None]:
        """Validate and extract 'id' and 'text' fields from a single API item dictionary.

        Args:
            item: The dictionary representing a single API item.
            group_key: The key of the polling group for logging context.

        Returns:
            A tuple containing the node ID with suffix and the item's text value,
            or (None, None) if validation fails.

        """
        api_id_value = item.get("id")
        if not isinstance(api_id_value, int | str):
            _PROCESSOR_LOGGER.warning(
                "API item in group '%s' has invalid 'id' type. Item: %s. Skipping.",
                group_key,
                format_for_log(item),
            )
            return None, None

        node_id_with_suffix = str(api_id_value).strip()
        if not node_id_with_suffix:
            _PROCESSOR_LOGGER.warning(
                "API item in group '%s' has empty 'id'. Item: %s. Skipping.",
                group_key,
                format_for_log(item),
            )
            return None, None

        item_text_value = item.get("text")
        if item_text_value is None:
            _PROCESSOR_LOGGER.warning(
                "API item for node '%s' in group '%s' missing 'text'. Item: %s. Skipping.",
                node_id_with_suffix,
                group_key,
                format_for_log(item),
            )
            return node_id_with_suffix, None

        # Ensure item_text_value is always treated as a string for consistency
        # The API is expected to return values that can be stringified.
        try:
            parsed_text = str(item_text_value)
        except Exception as e:
            _PROCESSOR_LOGGER.warning(
                "API item text for node '%s' could not be converted to string. Value: %s, Error: %s. Skipping.",
                node_id_with_suffix,
                format_for_log(item_text_value),
                e,
            )
            return node_id_with_suffix, None
        return node_id_with_suffix, parsed_text

    def _should_ignore_polled_item(
        self, node_id_clean: str, item_text_value: Any, group_key_for_log: str
    ) -> bool:
        """Determine if a polled API item should be ignored due to a recent set operation.

        If a node was recently set via the API, and the polled value differs from
        the current coordinator value, the polled value is ignored to prevent
        race conditions and UI bouncing.

        Args:
            node_id_clean: The cleaned node ID (without suffix).
            item_text_value: The text value received from the API for this node.
            group_key_for_log: The key of the polling group for logging context.

        Returns:
            True if the polled item should be ignored, False otherwise.

        """
        last_set_time_for_node = self._coordinator._last_set_times.get(
            node_id_clean, 0.0
        )
        timeout_duration = self._coordinator.entry.options.get(
            CONF_RECENTLY_SET_POLL_IGNORE_WINDOW_S,
            DEFAULT_RECENTLY_SET_POLL_IGNORE_WINDOW_S,
        )
        current_time_monotonic = time.monotonic()

        if was_recently_set := (
            last_set_time_for_node > 0.0
            and (current_time_monotonic - last_set_time_for_node) < timeout_duration
        ):
            current_coordinator_value = self._coordinator.data.get(node_id_clean)
            # Ensure both values are strings for comparison, handling None
            str_current_coordinator_value = (
                str(current_coordinator_value)
                if current_coordinator_value is not None
                else None
            )
            str_item_text_value = (
                str(item_text_value) if item_text_value is not None else None
            )

            _LOGGER.debug(
                "Processor: _should_ignore_polled_item check for node '%s'. Recently set: %s. Polled value: '%s', Coordinator value: '%s'.",
                node_id_clean,
                was_recently_set,
                item_text_value,
                current_coordinator_value,
            )

            if str_current_coordinator_value != str_item_text_value:
                _LOGGER.warning(
                    "Processor: Ignoring polled value '%s' for node '%s' (group '%s'). Node was recently set via API (at %.2f, current time %.2f, window: %ss). Coordinator currently holds '%s'. Polled value ignored.",
                    item_text_value,
                    node_id_clean,
                    group_key_for_log,
                    last_set_time_for_node,
                    current_time_monotonic,
                    timeout_duration,
                    current_coordinator_value,
                )
                return True
            _LOGGER.debug(
                "Processor: Polled value '%s' for node '%s' matches coordinator value '%s'. Node was recently set, but values match. Proceeding with polled value.",
                item_text_value,
                node_id_clean,
                current_coordinator_value,
            )
            return False
        _LOGGER.debug(
            "Processor: _should_ignore_polled_item check for node '%s'. Not recently set OR ignore window passed (last_set: %.2f, current_time: %.2f, window: %ss). Proceeding.",
            node_id_clean,
            last_set_time_for_node,
            current_time_monotonic,
            timeout_duration,
        )
        return False

    def _process_single_api_item(
        self,
        item: dict[str, Any],
        group_key: str,
        raw_ids_seen: set[str],
        cleaned_node_ids_processed: set[str],
    ) -> dict[str, Any] | None:
        """Process a single item from the API response list.

        This method validates the item, checks for duplicates (both raw and cleaned IDs),
        applies the ignore logic for recently set values, and updates the coordinator's
        data store.

        Args:
            item: The dictionary representing a single API item.
            group_key: The key of the polling group for logging context.
            raw_ids_seen: A set of raw node IDs already seen in the current batch.
            cleaned_node_ids_processed: A set of cleaned node IDs already processed in the current batch.

        Returns:
            The processed item dictionary if successful and not ignored, None otherwise.

        """
        node_id_with_suffix, item_text_value = (
            self._validate_and_extract_api_item_fields(item, group_key)
        )
        if node_id_with_suffix is None or item_text_value is None:
            return None

        if node_id_with_suffix in raw_ids_seen:
            _PROCESSOR_LOGGER.error(
                "Processor: Duplicate raw node ID '%s' in API response for group '%s'. Item: %s. Skipping.",
                node_id_with_suffix,
                group_key,
                format_for_log(item),
            )
            return None
        raw_ids_seen.add(node_id_with_suffix)

        node_id_clean = strip_hdg_node_suffix(node_id_with_suffix)

        # Retrieve the entity definition to pass to the parser
        # Ensure the node_id used for lookup in the registry has the 'T' suffix
        # as the registry stores them with the suffix.
        node_id_for_registry_lookup = node_id_with_suffix
        if not node_id_for_registry_lookup.endswith("T"):
            node_id_for_registry_lookup += "T"

        # Retrieve the entity definition to pass to the parser
        entity_definition = (
            self._coordinator.hdg_entity_registry.get_entity_definition_by_node_id(
                node_id_for_registry_lookup
            )
        )
        if not entity_definition:
            _PROCESSOR_LOGGER.warning(
                "Processor: No entity definition found for node ID '%s'. Skipping parsing.",
                node_id_for_registry_lookup,
            )
            return None

        # Parse the raw value using the dedicated parser
        parsed_value = parse_sensor_value(
            item_text_value,
            cast(dict[str, Any], entity_definition),
            node_id_for_log=node_id_clean,
            entity_id_for_log=entity_definition.get("translation_key"),
        )
        _LOGGER.debug(
            "Processor: Node %s (Raw: '%s', Parsed: '%s')",
            node_id_clean,
            item_text_value,
            parsed_value,
        )

        if self._should_ignore_polled_item(node_id_clean, parsed_value, group_key):
            return None

        if node_id_clean in cleaned_node_ids_processed:
            existing_value = self._coordinator.data.get(node_id_clean)
            if existing_value != parsed_value:
                _PROCESSOR_LOGGER.error(
                    "Processor: Duplicate base node ID '%s' (from API ID '%s') in API response for group '%s' WITH CONFLICTING VALUES. Existing: '%s', New (skipped): '%s'.",
                    node_id_clean,
                    node_id_with_suffix,
                    group_key,
                    format_for_log(existing_value),
                    format_for_log(parsed_value),
                )
            else:
                _PROCESSOR_LOGGER.debug(
                    "Processor: Duplicate base node ID '%s' (from API ID '%s') in API response for group '%s' with identical value. Existing: '%s', New (skipped): '%s'.",
                    node_id_clean,
                    node_id_with_suffix,
                    group_key,
                    format_for_log(existing_value),
                    format_for_log(parsed_value),
                )
            return None

        self._coordinator.data[node_id_clean] = parsed_value
        cleaned_node_ids_processed.add(node_id_clean)
        return item

    def parse_and_store_api_items(
        self,
        group_key: str,
        api_items: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        """Parse, validate, and store API items from a polling group response.

        This is the main entry point for processing a list of raw API items.
        It iterates through each item, processes it individually, and updates
        the coordinator's data store.

        Args:
            group_key: The key of the polling group being processed.
            api_items: A list of dictionaries, each representing a raw API item.

        Returns:
            A list of successfully processed items.

        """
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
