"""Tests for the polling response processor (parse → validate → store).

Stdlib only - the coordinator is stubbed with the exact surface the
processor uses (entry.options, data, optimistic, registry lookup,
update_node). Behavior verified against a live probe run of
process_api_items.

    ../.venv/bin/python -m pytest tests/ -q
"""

from __future__ import annotations

import os
import sys
import unittest
from types import SimpleNamespace
from typing import Any, cast

sys.path.insert(
    0,
    os.path.join(os.path.dirname(__file__), ".."),
)

from custom_components.hdg_boiler.classes.polling_response_processor import (
    HdgPollingResponseProcessor,
)
from custom_components.hdg_boiler.const import POLLING_GROUP_DEFINITIONS
from custom_components.hdg_boiler.definitions import get_sensor_definitions
from custom_components.hdg_boiler.registry import HdgEntityRegistry


def _make_processor(
    recently_set: set[str] | None = None,
) -> tuple[Any, HdgPollingResponseProcessor]:
    registry = HdgEntityRegistry(get_sensor_definitions({}), POLLING_GROUP_DEFINITIONS)
    data: dict[str, object] = {}
    # cast: the stub matches only the surface the processor touches
    coord = cast(
        Any,
        SimpleNamespace(
            entry=SimpleNamespace(options={}),
            data=data,
            optimistic=SimpleNamespace(
                is_recently_set=lambda node_id, window: (
                    node_id in (recently_set or set())
                )
            ),
            hdg_entity_registry=SimpleNamespace(
                get_entity_definition_by_node_id=(
                    registry.get_entity_definition_by_node_id
                )
            ),
            update_node=lambda node_id, value: data.__setitem__(node_id, value),
        ),
    )
    return coord, HdgPollingResponseProcessor(coord)


class ProcessApiItems(unittest.TestCase):
    def test_parses_and_stores_temperature(self) -> None:
        coord, proc = _make_processor()
        proc.process_api_items("group_1", [{"id": "22003T", "text": "65.5"}])
        # Storage key is the base node id (no T suffix).
        self.assertEqual(coord.data, {"22003": 65.5})

    def test_first_duplicate_wins_conflicting_value_skipped(self) -> None:
        coord, proc = _make_processor()
        proc.process_api_items(
            "group_1",
            [
                {"id": "22003T", "text": "65.5"},
                {"id": "22003T", "text": "70.0"},
            ],
        )
        self.assertEqual(coord.data, {"22003": 65.5})

    def test_identical_duplicate_stored_once(self) -> None:
        coord, proc = _make_processor()
        proc.process_api_items(
            "group_1",
            [
                {"id": "22003T", "text": "65.5"},
                {"id": "22003T", "text": "65.5"},
            ],
        )
        self.assertEqual(coord.data, {"22003": 65.5})

    def test_missing_id_or_text_skipped(self) -> None:
        coord, proc = _make_processor()
        proc.process_api_items(
            "group_1",
            [{"id": "", "text": "x"}, {"id": "22003T"}],
        )
        self.assertEqual(coord.data, {})

    def test_unknown_node_id_skipped(self) -> None:
        coord, proc = _make_processor()
        proc.process_api_items("group_1", [{"id": "99999T", "text": "1"}])
        self.assertEqual(coord.data, {})

    def test_non_list_response_ignored(self) -> None:
        coord, proc = _make_processor()
        # a malformed payload arrives as a non-list and must be dropped whole
        proc.process_api_items("group_1", cast(Any, {"id": "22003T"}))
        self.assertEqual(coord.data, {})

    def test_recently_set_diverging_poll_is_ignored(self) -> None:
        coord, proc = _make_processor(recently_set={"22003"})
        coord.data["22003"] = 70.0  # optimistic value from a recent SET
        proc.process_api_items("group_1", [{"id": "22003T", "text": "65.5"}])
        self.assertEqual(coord.data["22003"], 70.0)

    def test_recently_set_matching_poll_passes(self) -> None:
        coord, proc = _make_processor()
        coord.data["22003"] = 65.5
        proc.process_api_items("group_1", [{"id": "22003T", "text": "65.5"}])
        self.assertEqual(coord.data["22003"], 65.5)


if __name__ == "__main__":
    unittest.main()
