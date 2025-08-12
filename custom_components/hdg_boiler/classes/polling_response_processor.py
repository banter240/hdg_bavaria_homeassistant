"""Processor for handling and parsing API responses for the HDG Bavaria Boiler.

This class encapsulates the logic for validating, transforming, and storing raw
API response data. It works in conjunction with the `HdgDataUpdateCoordinator`
to manage the state of boiler data nodes.
"""

from __future__ import annotations

__version__ = "0.4.0"

import logging
import time
from typing import TYPE_CHECKING, Any, cast

from ..const import (
    CONF_RECENTLY_SET_POLL_IGNORE_WINDOW_S,
    DEFAULT_RECENTLY_SET_POLL_IGNORE_WINDOW_S,
    PROCESSOR_LOGGER_NAME,
)
from ..helpers.logging_utils import _LOGGER, format_for_log
from ..helpers.parsers import parse_sensor_value
from ..helpers.string_utils import strip_hdg_node_suffix

if TYPE_CHECKING:
    from ..coordinator import HdgDataUpdateCoordinator
    from ..models import SensorDefinition

_PROCESSOR_LOGGER = logging.getLogger(PROCESSOR_LOGGER_NAME)


class HdgPollingResponseProcessor:
    """Processes raw API polling responses."""

    def __init__(self, coordinator: HdgDataUpdateCoordinator) -> None:
        """Initialize the HdgPollingResponseProcessor."""
        self._coordinator = coordinator
        _PROCESSOR_LOGGER.debug("HdgPollingResponseProcessor initialized.")

    def _get_entity_definition(
        self, node_id_with_suffix: str
    ) -> SensorDefinition | None:
        """Retrieve the entity definition for a given node ID."""
        node_id_for_lookup = (
            node_id_with_suffix
            if node_id_with_suffix.endswith("T")
            else f"{node_id_with_suffix}T"
        )
        definition = (
            self._coordinator.hdg_entity_registry.get_entity_definition_by_node_id(
                node_id_for_lookup
            )
        )
        if not definition:
            _PROCESSOR_LOGGER.warning(
                "No entity definition found for node ID '%s'.", node_id_for_lookup
            )
        return definition

    def _is_recently_set(self, node_id: str) -> bool:
        """Check if a node's value was recently set via an API call."""
        # Accesses the refactored state in the coordinator
        last_set_time = self._coordinator._setter_state["last_set_times"].get(
            node_id, 0.0
        )
        if last_set_time == 0.0:
            return False

        timeout = cast(
            float,
            self._coordinator.entry.options.get(
                CONF_RECENTLY_SET_POLL_IGNORE_WINDOW_S,
                DEFAULT_RECENTLY_SET_POLL_IGNORE_WINDOW_S,
            ),
        )
        return (time.monotonic() - last_set_time) < timeout

    def _should_ignore_polled_value(
        self, node_id: str, parsed_polled_value: Any, group_key: str
    ) -> bool:
        """Determine if a polled value should be ignored to prevent race conditions."""
        if not self._is_recently_set(node_id):
            return False

        current_value = self._coordinator.data.get(node_id)
        if current_value != parsed_polled_value:
            _LOGGER.warning(
                "Ignoring polled value for node '%s' in group '%s' due to recent set. "
                "Coordinator holds '%s', polled value was '%s'.",
                node_id,
                group_key,
                format_for_log(current_value),
                format_for_log(parsed_polled_value),
            )
            return True

        _LOGGER.debug(
            "Polled value for recently set node '%s' matches coordinator value. Processing.",
            node_id,
        )
        return False

    def _handle_duplicate_node_id(
        self, node_id: str, new_value: Any, group_key: str, api_id: str
    ) -> None:
        """Handle cases where a cleaned node ID is already processed in the same batch."""
        existing_value = self._coordinator.data.get(node_id)
        log_message = (
            "Duplicate base node ID '%s' (from API ID '%s') in group '%s' with %s value. "
            "Existing: '%s', New (skipped): '%s'."
        )
        if existing_value != new_value:
            _PROCESSOR_LOGGER.error(
                log_message,
                node_id,
                api_id,
                group_key,
                "conflicting",
                format_for_log(existing_value),
                format_for_log(new_value),
            )
        else:
            _PROCESSOR_LOGGER.debug(
                log_message,
                node_id,
                api_id,
                group_key,
                "identical",
                format_for_log(existing_value),
                format_for_log(new_value),
            )

    def _process_single_item(
        self,
        item: dict[str, Any],
        group_key: str,
        processed_ids: set[str],
    ) -> None:
        """Process a single item from the API response."""
        api_id = str(item.get("id", "")).strip()
        raw_value = item.get("text")

        if not api_id or raw_value is None:
            _PROCESSOR_LOGGER.warning(
                "API item in group '%s' is invalid (missing id/text): %s. Skipping.",
                group_key,
                format_for_log(item),
            )
            return

        node_id = strip_hdg_node_suffix(api_id)
        definition = self._get_entity_definition(api_id)
        if not definition:
            return

        parsed_value = parse_sensor_value(
            str(raw_value),
            cast(dict[str, Any], definition),
            node_id_for_log=node_id,
            entity_id_for_log=definition.get("translation_key"),
        )

        if self._should_ignore_polled_value(node_id, parsed_value, group_key):
            return

        if node_id in processed_ids:
            self._handle_duplicate_node_id(node_id, parsed_value, group_key, api_id)
            return

        self._coordinator.data[node_id] = parsed_value
        processed_ids.add(node_id)

    def process_api_items(
        self,
        group_key: str,
        api_items: list[dict[str, Any]],
    ) -> None:
        """Parse, validate, and store API items from a polling group response."""
        if not isinstance(api_items, list):
            _PROCESSOR_LOGGER.warning(
                "Invalid API response for group '%s': expected a list, got %s.",
                group_key,
                type(api_items).__name__,
            )
            return

        processed_ids_this_call: set[str] = set()
        for item in api_items:
            if isinstance(item, dict):
                self._process_single_item(item, group_key, processed_ids_this_call)
            else:
                _PROCESSOR_LOGGER.warning(
                    "API item in group '%s' is not a dictionary: %s. Skipping.",
                    group_key,
                    format_for_log(item),
                )
