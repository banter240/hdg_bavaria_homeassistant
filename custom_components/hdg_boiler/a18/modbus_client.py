"""Minimal async Modbus TCP client for the HDG A18 (Lambda OEM).

The Lambda controller only supports function codes 0x03 (read holding
registers) and 0x10 (write multiple registers). It closes the connection
after 60 s without traffic, so the client reconnects on demand and retries
a failed request once.

Stdlib only - no pip dependencies, no Home Assistant imports.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import struct

__all__ = [
    "ModbusError",
    "ModbusConnectionError",
    "ModbusExceptionResponse",
    "ModbusTcpClient",
]

_LOGGER = logging.getLogger(__name__)

MAX_READ_REGISTERS = 125
MAX_WRITE_REGISTERS = 123


class ModbusError(Exception):
    """Base class for all Modbus errors."""


class ModbusConnectionError(ModbusError):
    """Connection failed, dropped, or timed out."""


class ModbusExceptionResponse(ModbusError):
    """The device replied with a Modbus exception code (e.g. 2 = bad address)."""

    def __init__(self, function: int, code: int) -> None:
        """Store the failing function code and the reported exception code."""
        super().__init__(f"Modbus exception {code} for function 0x{function:02X}")
        self.function = function
        self.code = code


class ModbusTcpClient:
    """Modbus TCP client with automatic reconnection."""

    def __init__(
        self, host: str, port: int = 502, unit_id: int = 1, timeout: float = 5.0
    ) -> None:
        """Store connection parameters; no socket opens until the first call."""
        self._host = host
        self._port = port
        self._unit_id = unit_id
        self._timeout = timeout
        self._reader: asyncio.StreamReader | None = None
        self._writer: asyncio.StreamWriter | None = None
        self._transaction_id = 0
        self._lock = asyncio.Lock()

    async def _connect(self) -> None:
        if self._writer is not None and not self._writer.is_closing():
            return
        try:
            self._reader, self._writer = await asyncio.wait_for(
                asyncio.open_connection(self._host, self._port), self._timeout
            )
        except (OSError, TimeoutError) as err:
            self._reader = self._writer = None
            raise ModbusConnectionError(
                f"Connection to {self._host}:{self._port} failed: {err!r}"
            ) from err

    async def _disconnect(self) -> None:
        writer, self._reader, self._writer = self._writer, None, None
        if writer is not None:
            writer.close()
            with contextlib.suppress(OSError, TimeoutError):
                await writer.wait_closed()

    async def close(self) -> None:
        """Close the connection (the client reconnects on the next call)."""
        async with self._lock:
            await self._disconnect()

    async def _request(self, pdu: bytes) -> bytes:
        """Send a PDU and return the response PDU, retrying once on failure."""
        async with self._lock:
            last_error: Exception | None = None
            for attempt in (1, 2):
                try:
                    await self._connect()
                    assert self._reader is not None and self._writer is not None
                    self._transaction_id = (self._transaction_id + 1) & 0xFFFF
                    tid = self._transaction_id
                    frame = (
                        struct.pack(">HHHB", tid, 0, len(pdu) + 1, self._unit_id) + pdu
                    )
                    self._writer.write(frame)
                    await asyncio.wait_for(self._writer.drain(), self._timeout)
                    header = await asyncio.wait_for(
                        self._reader.readexactly(7), self._timeout
                    )
                    rtid, proto, length, _unit = struct.unpack(">HHHB", header)
                    if proto != 0 or length < 2 or length > 260:
                        raise ModbusConnectionError("Invalid MBAP header")
                    body = await asyncio.wait_for(
                        self._reader.readexactly(length - 1), self._timeout
                    )
                    if rtid != tid:
                        raise ModbusConnectionError(
                            f"Transaction ID mismatch ({rtid} != {tid})"
                        )
                    return body
                except (
                    OSError,
                    asyncio.IncompleteReadError,
                    TimeoutError,
                    ModbusConnectionError,
                ) as err:
                    last_error = err
                    await self._disconnect()
                    if attempt == 1:
                        _LOGGER.debug("Request failed (%r), retrying", last_error)
            raise ModbusConnectionError(
                f"Communication with {self._host}:{self._port} failed: {last_error!r}"
            ) from last_error

    async def read_holding_registers(self, address: int, count: int) -> list[int]:
        """Return `count` holding registers as unsigned 16-bit values (FC 0x03)."""
        if not 1 <= count <= MAX_READ_REGISTERS:
            raise ValueError("count must be between 1 and 125")
        resp = await self._request(struct.pack(">BHH", 0x03, address, count))
        if resp[0] == 0x83:
            raise ModbusExceptionResponse(0x03, resp[1] if len(resp) > 1 else -1)
        if (
            resp[0] != 0x03
            or len(resp) < 2
            or resp[1] != count * 2
            or len(resp) != 2 + count * 2
        ):
            raise ModbusConnectionError(f"Unexpected response: {resp.hex()}")
        return list(struct.unpack(f">{count}H", resp[2:]))

    async def write_registers(self, address: int, values: list[int]) -> None:
        """Write registers via FC 0x10 (single registers must go this way too).

        Values may be signed; they are mapped onto 16 bits. Not wired to any
        entity - kept for a future generation with write support.
        """
        count = len(values)
        if not 1 <= count <= MAX_WRITE_REGISTERS:
            raise ValueError("register count must be between 1 and 123")
        words = [v & 0xFFFF for v in values]
        pdu = struct.pack(">BHHB", 0x10, address, count, count * 2) + struct.pack(
            f">{count}H", *words
        )
        resp = await self._request(pdu)
        if resp[0] == 0x90:
            raise ModbusExceptionResponse(0x10, resp[1] if len(resp) > 1 else -1)
        if resp[0] != 0x10 or len(resp) != 5:
            raise ModbusConnectionError(f"Unexpected response: {resp.hex()}")
        raddr, rcount = struct.unpack(">HH", resp[1:])
        if raddr != address or rcount != count:
            raise ModbusConnectionError("Write reply does not match the request")
