"""HDG A18 backend (Lambda OEM) via Modbus TCP.

Standalone by design: stdlib only and no Home Assistant imports, so the
unit tests exercise it against a fake Modbus server without an HA test
harness. Production code imports it as ``hdg_boiler.a18``.
"""

from __future__ import annotations

from .modbus_client import (
    ModbusConnectionError,
    ModbusError,
    ModbusExceptionResponse,
    ModbusTcpClient,
)
from .polling import due_groups
from .registers import (
    ENUMS,
    REGISTERS,
    REGISTER_BLOCKS,
    REGISTER_GROUPS,
    decode_all,
    enum_options,
)
from .start_counter import StartCounter

__all__ = [
    "ModbusConnectionError",
    "ModbusError",
    "ModbusExceptionResponse",
    "ModbusTcpClient",
    "due_groups",
    "ENUMS",
    "REGISTERS",
    "REGISTER_BLOCKS",
    "REGISTER_GROUPS",
    "decode_all",
    "enum_options",
    "StartCounter",
]
