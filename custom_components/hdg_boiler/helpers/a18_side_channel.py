"""Modbus side channel for the HDG A18 (Lambda OEM heat pump).

Bridges the stdlib-only ``hdg_boiler.a18`` backend into the coordinator:
reads the register groups over Modbus TCP, decodes them, and writes the
pseudo nodes (``a18:<key>``) into the coordinator data store. The WebControl
HTTP transport keeps serving every other polling group untouched.

Registers from slower poll groups are retained between fetches so slow
values survive until their own group is due again. The compressor start
counter persists across restarts via the HA store.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from homeassistant.helpers.storage import Store

from ..a18 import (
    REGISTER_GROUPS,
    ModbusExceptionResponse,
    ModbusTcpClient,
    StartCounter,
    decode_all,
)
from ..const import A18_MODBUS_GROUP_PREFIX, A18_NODE_PREFIX

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant

__all__ = ["HdgA18SideChannel"]

_LOGGER = logging.getLogger(__name__)

_STARTS_STORE_VERSION = 1


class HdgA18SideChannel:
    """Fetches the A18 Modbus poll groups for the coordinator."""

    def __init__(
        self,
        hass: HomeAssistant,
        host: str,
        port: int,
        slave_id: int,
        int32_order: str,
        entry_id: str,
    ) -> None:
        """Create the Modbus client; no socket opens until the first poll."""
        self._hass = hass
        self._int32_order = int32_order
        self._client = ModbusTcpClient(host, port, slave_id)
        self._regs: dict[int, int] = {}
        self._store: Store[dict[str, Any]] = Store(
            hass, _STARTS_STORE_VERSION, f"a18_starts_{entry_id}"
        )
        self.starts = StartCounter()

    @classmethod
    def is_a18_group(cls, group_key: str) -> bool:
        """Whether a polling-group key belongs to the Modbus side channel."""
        return group_key.startswith(A18_MODBUS_GROUP_PREFIX)

    async def async_load_state(self) -> None:
        """Restore the compressor start counter after a restart."""
        self.starts = StartCounter.from_dict(await self._store.async_load())

    async def _read_block(self, start: int, count: int) -> None:
        """Read one block; on an exception reply read registers one by one."""
        try:
            values = await self._client.read_holding_registers(start, count)
            self._regs.update({start + i: v for i, v in enumerate(values)})
            return
        except ModbusExceptionResponse as err:
            _LOGGER.debug(
                "Block %s+%s rejected (%s), reading registers one by one.",
                start,
                count,
                err,
            )
        for address in range(start, start + count):
            try:
                self._regs[address] = (
                    await self._client.read_holding_registers(address, 1)
                )[0]
            except ModbusExceptionResponse:
                _LOGGER.debug("Register %s not readable.", address)

    async def fetch_group(self, group_key: str, update_node: Any) -> bool:
        """Read one A18 poll group and push decoded pseudo nodes.

        Retained registers keep older groups' values alive; decode_all sees
        the union, so slow sensors hold their state between their own polls.
        Returns True on success. Modbus failures never take the WebControl
        coordinator offline — the regular group-retry backoff handles them.
        """
        suffix = group_key.removeprefix(A18_MODBUS_GROUP_PREFIX)
        blocks = REGISTER_GROUPS[suffix]
        try:
            for start, count in blocks:
                await self._read_block(start, count)
        except Exception as err:  # noqa: BLE001 - transport errors vary widely
            _LOGGER.warning("A18 Modbus fetch for '%s' failed: %s", group_key, err)
            return False

        decoded = decode_all(self._regs, self._int32_order)
        before = self.starts.as_dict()
        self.starts.update(decoded.get("wp_status"))
        if self.starts.as_dict() != before:
            self._store.async_delay_save(self.starts.as_dict, 10)
        decoded["kompressorstarts"] = self.starts.count

        for key, value in decoded.items():
            update_node(f"{A18_NODE_PREFIX}{key}", value)
        return True

    async def async_close(self) -> None:
        """Close the TCP connection (the client reconnects on demand)."""
        await self._client.close()
