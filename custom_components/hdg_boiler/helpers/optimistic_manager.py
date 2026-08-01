"""Manages optimistic state for SET_NODE operations.

After a user sets a value, we immediately show the new value in the UI
(optimistic update) before the API confirms it. The grace period prevents
polled values from overwriting an in-flight SET.
"""

from __future__ import annotations

__all__ = ["HdgOptimisticManager"]

import time


class HdgOptimisticManager:
    """Track optimistic state for SET_NODE operations.

    Usage:
        # Coordinator, before queuing SET_NODE:
        self.optimistic.set(node_id, value)

        # Entity, when reading state:
        if (opt := coordinator.get_optimistic_value(node_id)) is not None:
            return opt  # Show optimistic value
        return coordinator.data[node_id]  # Fall back to polled value

        # Executor, in finally block:
        self.optimistic.clear(node_id)  # Always cleanup after SET
    """

    def __init__(self) -> None:
        """Initialize the optimistic state store."""
        # {node_id: (value, set_monotonic_time, grace_period_s)}
        self._store: dict[str, tuple[str, float, float]] = {}

    def set(
        self,
        node_id: str,
        value: str,
        grace_period: float | None = None,
    ) -> None:
        """Record an optimistic value. Called BEFORE queuing a SET_NODE request.

        Args:
            node_id: The boiler node ID being set.
            value: The value sent to the API.
            grace_period: How long (seconds) to guard against poll overwrites.
                          Defaults to OPTIMISTIC_GRACE_PERIOD_S from const.

        """
        from ..const import OPTIMISTIC_GRACE_PERIOD_S

        self._store[node_id] = (
            value,
            time.monotonic(),
            grace_period or OPTIMISTIC_GRACE_PERIOD_S,
        )

    def get(self, node_id: str) -> str | None:
        """Return optimistic value if still within grace period, else None.

        Also evicts the entry if it has expired, so the store self-cleans.
        """
        entry = self._store.get(node_id)
        if entry is None:
            return None
        value, set_time, grace = entry
        if (time.monotonic() - set_time) < grace:
            return value
        del self._store[node_id]
        return None

    def clear(self, node_id: str) -> None:
        """Remove optimistic state for a node.

        Called in the finally block of SET_NODE execution so the polled
        value takes over on the next coordinator update.
        """
        self._store.pop(node_id, None)

    def cleanup(self) -> None:
        """Evict all expired entries in one pass.

        Called periodically (e.g. after each polling cycle) to prevent
        indefinite accumulation of entries for nodes that are never polled again.
        """
        now = time.monotonic()
        expired = [
            nid
            for nid, (_, set_time, grace) in self._store.items()
            if (now - set_time) >= grace
        ]
        for nid in expired:
            del self._store[nid]

    def is_recently_set(self, node_id: str, window_s: float) -> bool:
        """Return True if node was SET within the last window_s seconds.

        Used by the polling processor to skip overwriting values that are
        still in-flight (coordinator has a configurable ignore window).
        """
        entry = self._store.get(node_id)
        if entry is None:
            return False
        _, set_time, _ = entry
        return (time.monotonic() - set_time) < window_s
