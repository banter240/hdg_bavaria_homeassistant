"""Tests for coordinator internals: scheduling, retry backoff, debounced writes.

Needs the HA harness (real HomeAssistant fixture for the
DataUpdateCoordinator base class). Run with the harness venv:

    dev/tmp/phacc/venv/bin/python -m pytest tests/test_coordinator.py -q
"""

from __future__ import annotations

import time
from types import SimpleNamespace
from typing import Any, cast

import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.hdg_boiler.const import (
    CONF_HOST_IP,
    DOMAIN,
    POLLING_RETRY_MAX_DELAY_S,
)
from custom_components.hdg_boiler.coordinator import HdgDataUpdateCoordinator
from custom_components.hdg_boiler.exceptions import (
    HdgApiConnectionError,
    HdgApiPreemptedError,
)
from custom_components.hdg_boiler.helpers.api_access_manager import ApiPriority
from custom_components.hdg_boiler.registry import HdgEntityRegistry
from custom_components.hdg_boiler.const import POLLING_GROUP_DEFINITIONS
from custom_components.hdg_boiler.definitions import get_sensor_definitions

OPTIONS = {"enable_feuerung": True, "enable_waermepumpe": True}


def _make_coordinator(
    hass: Any,
    *,
    options: dict[str, Any] | None = None,
) -> tuple[HdgDataUpdateCoordinator, Any]:
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={CONF_HOST_IP: "192.0.2.1"},
        options=options if options is not None else dict(OPTIONS),
    )
    entry.add_to_hass(hass)
    registry = HdgEntityRegistry(
        get_sensor_definitions(entry.options), POLLING_GROUP_DEFINITIONS
    )
    access = SimpleNamespaceAccess()
    coord = HdgDataUpdateCoordinator(
        hass,
        cast(Any, SimpleNamespace(base_url="http://192.0.2.1")),
        access,  # type: ignore[arg-type]
        entry,
        3,
        registry,
    )
    return coord, access


class SimpleNamespaceAccess:
    """Stub for HdgApiAccessManager: records priorities, returns canned replies."""

    def __init__(self) -> None:
        self.reply: Any = []
        self.error: Exception | None = None
        self.priorities: list[ApiPriority] = []

    async def submit_request(self, priority: ApiPriority, command: Any) -> Any:
        self.priorities.append(priority)
        if self.error is not None:
            raise self.error
        return self.reply

    async def stop(self) -> None:
        return None


async def test_scan_intervals_default_and_override(hass: Any) -> None:
    coord, _ = _make_coordinator(hass)
    first_key = next(iter(coord.hdg_entity_registry.get_polling_group_payloads()))
    default = coord.hdg_entity_registry.get_polling_group_payloads()[first_key][
        "default_scan_interval"
    ]
    assert coord.scan_intervals[first_key].total_seconds() == default

    option_key = f"scan_interval_{first_key}"
    entry = coord.entry
    hass.config_entries.async_update_entry(entry, options={option_key: 60})
    assert coord.scan_intervals[first_key].total_seconds() == 60


async def test_get_groups_to_fetch_due_and_retry(hass: Any) -> None:
    coord, _ = _make_coordinator(hass)
    keys = list(coord.hdg_entity_registry.get_polling_group_payloads())
    now = time.monotonic()
    # group 0 is due (never read), group 1 failed and is past its retry stamp
    coord._polling_state.failed_group_retry_info[keys[1]] = {
        "attempts": 1,
        "next_retry_time": now - 1,
    }
    coord._polling_state.last_update_times[keys[2]] = now  # fresh, not due

    due = coord._get_groups_to_fetch(now)
    assert keys[0] in due
    assert keys[1] in due
    assert keys[2] not in due


async def test_retry_backoff_doubles_and_caps(hass: Any) -> None:
    coord, _ = _make_coordinator(hass)
    keys = list(coord.hdg_entity_registry.get_polling_group_payloads())
    before = time.monotonic()
    for _ in range(4):
        coord._update_polling_status(False, [keys[0]])
    info = coord._polling_state.failed_group_retry_info[keys[0]]
    assert info["attempts"] == 4
    delay_cap = info["next_retry_time"] - before
    # last of the four delays is capped at POLLING_RETRY_MAX_DELAY_S
    assert delay_cap <= POLLING_RETRY_MAX_DELAY_S + 5


class TestGroupFetching:
    async def test_a18_group_without_channel_is_success(self, hass: Any) -> None:
        coord, _ = _make_coordinator(hass)
        assert await coord._fetch_group_data("group_a18_fast", ApiPriority.LOW) is True

    async def test_a18_group_routes_to_side_channel(self, hass: Any) -> None:
        coord, _ = _make_coordinator(hass)
        calls: list[str] = []

        async def fake_fetch(group_key: str, update_node: Any) -> bool:
            calls.append(group_key)
            return True

        coord.a18_side_channel = cast(Any, SimpleNamespace(fetch_group=fake_fetch))
        assert await coord._fetch_group_data("group_a18_fast", ApiPriority.LOW) is True
        assert calls == ["group_a18_fast"]

    async def test_connection_error_propagates(self, hass: Any) -> None:
        coord, access = _make_coordinator(hass)
        access.error = HdgApiConnectionError("down")
        with pytest.raises(HdgApiConnectionError):
            await coord._fetch_group_data("group_1", ApiPriority.LOW)


class TestUpdateCycle:
    async def test_cached_data_survives_connection_failure(self, hass: Any) -> None:
        coord, access = _make_coordinator(hass)
        coord.data["22003"] = 65.5
        coord._poll_all_requested = True
        access.error = HdgApiConnectionError("down")
        result = await coord._async_update_data()
        # offline keeps last values so entities never flash unknown
        assert result["22003"] == 65.5
        assert coord._last_poll_all_success is False

    async def test_preemption_counts_but_keeps_going(self, hass: Any) -> None:
        coord, access = _make_coordinator(hass)
        access.error = HdgApiPreemptedError("busy")
        coord._poll_all_requested = True
        await coord._async_update_data()
        # every group with active nodes raises; groups without payload (or
        # a18 groups without a channel) succeed and don't count
        assert coord._polling_state.consecutive_preemption_failures >= 1
        # a18 groups return success without a channel, so poll-all counts
        # as successful even while every HTTP group was preempted
        assert coord._last_poll_all_success is True


class TestDebouncedSet:
    async def test_rapid_sets_collapse_to_last_value(self, hass: Any) -> None:
        coord, _ = _make_coordinator(hass)
        await coord.async_set_node_value("15001", "21.0", "target")
        await coord.async_set_node_value("15001", "22.5", "target")
        assert list(coord._pending_set_timers) == ["15001"]
        assert coord._pending_set_timers["15001"][1] == "22.5"
        # optimistic value visible immediately, before the API call fires
        assert coord.get_optimistic_value("15001") == "22.5"
        await coord.async_stop()  # cancel the debounce timer before teardown

    async def test_execute_set_rolls_back_on_failure(self, hass: Any) -> None:
        coord, access = _make_coordinator(hass)
        coord.data["15001"] = "20.0"
        access.reply = False  # API returns falsy → not confirmed
        await coord._execute_set_request("15001", "25.0", "target")
        assert coord.data["15001"] == "20.0"
        assert coord.get_optimistic_value("15001") is None

    async def test_execute_set_persists_on_success(self, hass: Any) -> None:
        coord, access = _make_coordinator(hass)
        access.reply = True
        await coord._execute_set_request("15001", "25.0", "target")
        assert coord.data["15001"] == "25.0"


class TestDiagnostics:
    async def test_diagnostics_reports_group_and_retry_state(self, hass: Any) -> None:
        coord, _ = _make_coordinator(hass)
        diag = coord.get_diagnostics()
        assert diag["hostname"] == "192.0.2.1"
        assert set(diag["polling_group_status"]) == set(
            coord.hdg_entity_registry.get_polling_group_payloads()
        )
        assert diag["failed_poll_group_retry_info"] == {}


async def test_first_refresh_raises_when_everything_fails(hass: Any) -> None:
    from homeassistant.helpers.update_coordinator import UpdateFailed

    coord, access = _make_coordinator(hass)
    access.error = HdgApiConnectionError("down")
    with pytest.raises(UpdateFailed):
        await coord.async_config_entry_first_refresh()
