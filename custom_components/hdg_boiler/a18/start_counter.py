"""Compressor start counter for the HDG A18 (stdlib only).

Rule (verified against the Lambda status sequence): a start is the change
from idle (Stopp, Sperrzeit, Betriebsbereit, ...) into a running state.
Restarts after a defrost cycle do not count because the defrost does not
"arm" the idle latch. Mirrors the Lambda day counter.
"""

from __future__ import annotations

from typing import Any

IDLE_STATES = frozenset(
    {"Initialisierung", "Referenzierung", "Sperrzeit", "Betriebsbereit", "Stopp"}
)
RUNNING_STATES = frozenset(
    {"Pumpenstart", "Verdichterstart", "Vorregelbetrieb", "Regelbetrieb"}
)


class StartCounter:
    """Count compressor starts from the sequence of status values."""

    def __init__(self, count: int = 0, armed: bool = False) -> None:
        """Start at count; armed means an idle state was already seen."""
        self.count = count
        # armed: an idle state was seen, the next run is a start
        self.armed = armed

    def update(self, status: str | None) -> bool:
        """Process a status value; True if it counted a start."""
        if status in IDLE_STATES:
            self.armed = True
        elif status in RUNNING_STATES and self.armed:
            self.armed = False
            self.count += 1
            return True
        # Defrost, cooling, fault, error, unknown, None: state stays as is
        return False

    def as_dict(self) -> dict[str, Any]:
        """Return the persistent state (for the HA storage helper)."""
        return {"count": self.count, "armed": self.armed}

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> StartCounter:
        """Restore from HA storage; missing keys fall back to defaults."""
        data = data or {}
        return cls(int(data.get("count", 0)), bool(data.get("armed", False)))
