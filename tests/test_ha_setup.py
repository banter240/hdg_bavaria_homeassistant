"""Automated setup tests: config flow, options flow, duplicate protection.

Requires the HA test harness (pytest-homeassistant-custom-component), which
pins its own homeassistant release. Run with the isolated harness venv:

    dev/tmp/phacc/venv/bin/python -m pytest tests/test_ha_setup.py -q
"""

from __future__ import annotations

from typing import Any
from unittest.mock import patch

from custom_components.hdg_boiler.const import (
    ANLAGE_KESSEL,
    ANLAGE_WP,
    CONF_ANLAGENTYP,
    CONF_ENABLE_FEUERUNG,
    CONF_ENABLE_WAERMEPUMPE,
    CONF_HOST_IP,
    CONF_MODBUS_PORT,
    DOMAIN,
)

HOST = "192.0.2.1"  # TEST-NET-1, never routed


def _sections(**overrides: dict[str, Any]) -> dict[str, Any]:
    """Section payload for the init step; defaults come from the schema."""
    sections: dict[str, Any] = {
        "components": {},
        "a18_modbus": {},
        "puffer": {},
        "polling": {},
        "connection": {},
        "logging": {},
        "advanced": {},
    } | overrides
    return sections


def _no_entry_setup():
    """Keep flow tests out of the real setup path (it would hit the network)."""
    return patch("custom_components.hdg_boiler.async_setup_entry", return_value=True)


async def _run_through_flow(
    hass: Any,
    anlagentyp: str,
    sections: dict[str, Any] | None = None,
) -> Any:
    """Walk user → anlagentyp → init and return the flow result."""
    with (
        patch(
            "custom_components.hdg_boiler.config_flow._validate_host_connectivity",
            return_value=True,
        ),
        _no_entry_setup(),
    ):
        result = await hass.config_entries.flow.async_init(
            DOMAIN, context={"source": "user"}
        )
        assert result["type"] == "form"
        assert result["step_id"] == "user"

        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {CONF_HOST_IP: HOST}
        )
        assert result["type"] == "form"
        assert result["step_id"] == "anlagentyp"

        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {CONF_ANLAGENTYP: anlagentyp}
        )
        assert result["type"] == "form"
        assert result["step_id"] == "init"

        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], sections or _sections()
        )
    return result


async def test_user_flow_creates_entry(hass: Any) -> None:
    """The happy path reaches a config entry with host data and options."""
    result = await _run_through_flow(hass, ANLAGE_KESSEL)
    assert result["type"] == "create_entry"
    assert result["title"] == f"HDG Boiler ({HOST})"

    entry = hass.config_entries.async_entries(DOMAIN)[0]
    assert entry.data[CONF_HOST_IP] == HOST
    assert entry.options[CONF_ENABLE_FEUERUNG] is True
    assert entry.options["enable_waermepumpe"] is False


async def test_anlagentyp_preset_seeds_components(hass: Any) -> None:
    """Choosing the heat-pump preset flips the boiler toggle off."""
    result = await _run_through_flow(hass, ANLAGE_WP)
    assert result["type"] == "create_entry"

    entry = hass.config_entries.async_entries(DOMAIN)[0]
    assert entry.options[CONF_ENABLE_FEUERUNG] is False
    assert entry.options[CONF_ENABLE_WAERMEPUMPE] is True


async def test_duplicate_host_aborts(hass: Any) -> None:
    """A second flow for the same host aborts as already configured."""
    first = await _run_through_flow(hass, ANLAGE_KESSEL)
    assert first["type"] == "create_entry"

    with (
        patch(
            "custom_components.hdg_boiler.config_flow._validate_host_connectivity",
            return_value=True,
        ),
        _no_entry_setup(),
    ):
        result = await hass.config_entries.flow.async_init(
            DOMAIN, context={"source": "user"}
        )
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {CONF_HOST_IP: HOST.upper()}
        )

    assert result["type"] == "abort"
    assert result["reason"] == "already_configured"


async def test_unreachable_host_shows_error(hass: Any) -> None:
    """A failed connectivity check re-shows the user form with an error."""
    with patch(
        "custom_components.hdg_boiler.config_flow._validate_host_connectivity",
        return_value=False,
    ):
        result = await hass.config_entries.flow.async_init(
            DOMAIN, context={"source": "user"}
        )
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {CONF_HOST_IP: HOST}
        )

    assert result["type"] == "form"
    assert result["step_id"] == "user"
    assert result["errors"] == {"base": "cannot_connect"}


async def test_options_flow_updates_entry(hass: Any) -> None:
    """The options flow merges submitted sections into the stored options."""
    await _run_through_flow(hass, ANLAGE_KESSEL)
    entry = hass.config_entries.async_entries(DOMAIN)[0]

    result = await hass.config_entries.options.async_init(entry.entry_id)
    assert result["type"] == "form"
    assert result["step_id"] == "init"

    result = await hass.config_entries.options.async_configure(
        result["flow_id"],
        _sections(
            a18_modbus={"modbus_port": 503},
            components={CONF_ENABLE_WAERMEPUMPE: True},
        ),
    )
    assert result["type"] == "create_entry"

    assert entry.options[CONF_MODBUS_PORT] == 503
    assert entry.options[CONF_ENABLE_WAERMEPUMPE] is True
    # untouched keys persist across the options update
    assert entry.options[CONF_ENABLE_FEUERUNG] is True
    # unset puffer ids normalise to None instead of empty strings
    assert entry.options["puffer_mitte_oben_node_id"] is None
