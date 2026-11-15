"""Tests for the optimistic SET state manager.

Pure stdlib. Run with the shared venv:
    ../.venv/bin/python -m pytest tests/ -q
"""

from __future__ import annotations

import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from custom_components.hdg_boiler.helpers.optimistic_manager import (
    HdgOptimisticManager,
)


class OptimisticManagerTests(unittest.TestCase):
    def test_set_then_get_returns_value(self) -> None:
        mgr = HdgOptimisticManager()
        mgr.set("22003", "70.0")
        self.assertEqual(mgr.get("22003"), "70.0")

    def test_unset_node_returns_none(self) -> None:
        self.assertIsNone(HdgOptimisticManager().get("22003"))

    def test_clear_removes_state(self) -> None:
        mgr = HdgOptimisticManager()
        mgr.set("22003", "70.0")
        mgr.clear("22003")
        self.assertIsNone(mgr.get("22003"))

    def test_expired_entry_evicted_on_get(self) -> None:
        mgr = HdgOptimisticManager()
        # negative grace: entry is stale immediately (0.0 would fall back
        # to the default, which `or` treats as falsy)
        mgr.set("22003", "70.0", grace_period=-1.0)
        self.assertIsNone(mgr.get("22003"))
        self.assertNotIn("22003", mgr._store)

    def test_cleanup_drops_only_expired(self) -> None:
        mgr = HdgOptimisticManager()
        mgr.set("22003", "70.0")  # alive
        mgr.set("23001", "1", grace_period=-1.0)  # expired
        mgr.cleanup()
        self.assertIn("22003", mgr._store)
        self.assertNotIn("23001", mgr._store)


if __name__ == "__main__":
    unittest.main()
