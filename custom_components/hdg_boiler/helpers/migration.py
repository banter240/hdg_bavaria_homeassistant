"""Config entry migration steps for HDG Bavaria Boiler."""

from __future__ import annotations

from typing import Any

# Ordered list of (target_version, migration_fn) pairs.
# Each step runs when entry.version < target_version.
# Add new steps here when the config entry schema changes.
MIGRATION_STEPS: list[tuple[int, Any]] = []
