"""Pytest configuration bridging two test worlds.

The shared venv runs the stdlib suites (a18 backend, wire formats);
it must never trip over the missing HA harness. The harness venv in
dev/tmp/phacc (which pins its own homeassistant release) runs the
setup/flow suite; it opens no sockets, unlike the a18 client tests
that PHACC's socket gatekeeper would block.
"""

from __future__ import annotations

from collections.abc import Generator

import pytest

# The shared venv exposes a namespace-package phantom for this name
# (__file__ is None), so the real plugin module is what gets probed.
harness_ok = False
try:
    import importlib.util

    spec = importlib.util.find_spec("pytest_homeassistant_custom_component.plugins")
    harness_ok = spec is not None and spec.origin is not None
except ImportError:
    harness_ok = False

pytest_plugins = ["pytest_homeassistant_custom_component"] if harness_ok else []
# Two worlds, kept apart:
#   shared venv (no harness): stdlib suites only; HA suites need the
#   hass fixture and cannot collect.
#   harness venv: its socket gatekeeper blocks the a18 client tests and
#   its clock patching breaks the monotonic-based optimistic tests, so
#   the stdlib suites are excluded there instead.
collect_ignore = (
    ["test_a18.py", "test_protocols.py", "test_processor.py", "test_optimistic.py"]
    if harness_ok
    else ["test_ha_setup.py", "test_coordinator.py"]
)

if harness_ok:

    @pytest.fixture(autouse=True)
    def auto_enable_custom_integrations(
        enable_custom_integrations: None,
    ) -> Generator[None]:
        """Make the harness load custom_components/ for every test."""
        yield
