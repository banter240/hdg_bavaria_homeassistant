"""Poll-group scheduling for the HDG A18 backend (stdlib only)."""

from __future__ import annotations


def due_groups(
    now: float,
    last_read: dict[str, float],
    intervals: dict[str, float],
    tolerance: float = 0.0,
) -> list[str]:
    """Return the groups that must be read now.

    A group is due when it has never been read or its interval (minus a
    tolerance absorbing scheduler jitter) has elapsed.
    """
    return [
        group
        for group, interval in intervals.items()
        if group not in last_read or now - last_read[group] >= interval - tolerance
    ]
