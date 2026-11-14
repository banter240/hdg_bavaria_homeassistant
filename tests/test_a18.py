"""Tests for the HDG A18 backend: decoding, client, start counter, polling.

Stdlib unittest only - run with:
    ../.venv/bin/python -m unittest discover -s tests
"""

from __future__ import annotations

import asyncio
import os
import struct
import sys
import unittest
from typing import ClassVar, Final

sys.path.insert(
    0,
    os.path.join(os.path.dirname(__file__), "..", "custom_components", "hdg_boiler"),
)

import a18.modbus_client as mc  # noqa: E402
import a18.polling as polling  # noqa: E402
import a18.registers as rg  # noqa: E402
from a18.start_counter import StartCounter  # noqa: E402

# Register dump of the plant, 2026-11-13 (last readout of the
# lambda_heat_pumps integration).
LIVE_DUMP: Final[dict[int, int]] = {
    0: 0,
    1: 1,
    2: 65535,
    3: 0,
    4: 26,
    1000: 0,
    1001: 0,
    1002: 7,
    1003: 1,
    1004: 3965,
    1005: 3631,
    1006: 1353,
    1007: 65468,
    1008: 32768,
    1009: 0,
    1010: 2593,
    1011: 49,
    1012: 1141,
    1013: 425,
    1015: 2,
    1016: 370,
    1017: 320,
    1018: 50,
    1019: 0,
    1020: 36025,
    1021: 94,
    1022: 15402,
    1023: 433,
}


class DecodeTests(unittest.TestCase):
    def setUp(self) -> None:
        self.d = rg.decode_all(LIVE_DUMP, "low_first")

    def test_temperatures(self) -> None:
        self.assertEqual(self.d["vorlauf"], 39.65)
        self.assertEqual(self.d["ruecklauf"], 36.31)
        self.assertEqual(self.d["spreizung"], 3.34)
        self.assertEqual(self.d["quelle_ein"], -0.68)  # negative int16
        self.assertEqual(self.d["aussentemperatur"], -0.1)
        self.assertEqual(self.d["aussentemperatur_berechnet"], 2.6)

    def test_invalid_values(self) -> None:
        self.assertIsNone(self.d["quelle_aus"])  # 0x8000 = no measurement

    def test_power(self) -> None:
        self.assertEqual(self.d["volumenstrom"], 1353)
        self.assertEqual(self.d["verdichter"], 25.93)
        self.assertEqual(self.d["qp_heizen"], 4.9)
        self.assertEqual(self.d["leistung_el"], 1141)
        self.assertEqual(self.d["cop_geraet"], 4.25)

    def test_energy_counters_low_first(self) -> None:
        # matches the lambda_heat_pumps sensors: 6196 kWh / 28392 kWh / COP 4.58
        self.assertAlmostEqual(self.d["energie_el_kwh"], 6196.409, places=3)
        self.assertAlmostEqual(self.d["energie_th_kwh"], 28392.490, places=3)
        self.assertEqual(self.d["cop_gesamt"], 4.58)

    def test_energy_counters_high_first_implausible(self) -> None:
        d = rg.decode_all(LIVE_DUMP, "high_first")
        # wrong word order yields nonsense (negative here), not ~6196 kWh
        self.assertGreater(abs(d["energie_el_kwh"]), 100_000)

    def test_enums_and_derived(self) -> None:
        self.assertEqual(self.d["wp_status"], "Regelbetrieb")
        self.assertEqual(self.d["betriebszustand"], "Heizen")
        self.assertEqual(self.d["anf_typ"], "Heizen")
        self.assertEqual(self.d["betriebsmodus_regler"], "Automatik")
        self.assertEqual(self.d["fehlerzustand"], "Kein Fehler")
        self.assertIs(self.d["verdichter_laeuft"], True)
        self.assertIs(self.d["abtauung"], False)
        self.assertIs(self.d["heizstab_relais"], False)
        self.assertIs(self.d["stoerung"], False)

    def test_defrost_detected(self) -> None:
        regs = {**LIVE_DUMP, 1002: 10}
        self.assertIs(rg.decode_all(regs)["abtauung"], True)

    def test_unknown_enum_value(self) -> None:
        regs = {**LIVE_DUMP, 1002: 99}
        d = rg.decode_all(regs)
        self.assertEqual(d["wp_status"], rg.UNKNOWN)
        self.assertIn(d["wp_status"], rg.enum_options("wp_status"))

    def test_missing_registers_yield_none(self) -> None:
        d = rg.decode_all({1004: 3965})
        self.assertEqual(d["vorlauf"], 39.65)
        self.assertIsNone(d["ruecklauf"])
        self.assertIsNone(d["spreizung"])
        self.assertIsNone(d["cop_gesamt"])
        self.assertIsNone(d["abtauung"])

    def test_blocks_avoid_register_1014(self) -> None:
        addresses = {a for s, c in rg.REGISTER_BLOCKS for a in range(s, s + c)}
        self.assertNotIn(1014, addresses)
        for reg in rg.REGISTERS:
            width = 2 if reg.kind == rg.I32 else 1
            for off in range(width):
                self.assertIn(reg.address + off, addresses, reg.key)


class FakeModbusServer:
    """Modbus TCP server: FC 3 and FC 16, undefined addresses -> exception 2."""

    def __init__(self, registers: dict[int, int], close_after_first: bool = False):
        self.registers = dict(registers)
        self.close_after_first = close_after_first
        self.connections = 0
        self.writes: list[tuple[int, list[int]]] = []
        self._server: asyncio.AbstractServer | None = None

    async def start(self) -> int:
        self._server = await asyncio.start_server(self._handle, "127.0.0.1", 0)
        sockets = self._server.sockets
        assert sockets and sockets[0]
        return int(sockets[0].getsockname()[1])

    async def stop(self) -> None:
        assert self._server is not None
        self._server.close()
        await self._server.wait_closed()

    async def _handle(
        self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter
    ) -> None:
        self.connections += 1
        first = True
        try:
            while True:
                header = await reader.readexactly(7)
                tid, _proto, length, unit = struct.unpack(">HHHB", header)
                pdu = await reader.readexactly(length - 1)
                if self.close_after_first and not first:
                    # simulate the idle disconnect: drop without answering
                    writer.close()
                    return
                first = False
                func = pdu[0]
                if func == 16:
                    addr, count, _bytes = struct.unpack(">HHB", pdu[1:6])
                    words = struct.unpack(f">{count}H", pdu[6 : 6 + count * 2])
                    for i, w in enumerate(words):
                        self.registers[addr + i] = w
                    self.writes.append((addr, list(words)))
                    resp = struct.pack(">BHH", 16, addr, count)
                elif func == 3:
                    addr, count = struct.unpack(">HH", pdu[1:5])
                    if all(a in self.registers for a in range(addr, addr + count)):
                        data = struct.pack(
                            f">{count}H",
                            *[self.registers[a] for a in range(addr, addr + count)],
                        )
                        resp = bytes([3, count * 2]) + data
                    else:
                        resp = bytes([0x83, 2])
                else:
                    resp = bytes([func | 0x80, 1])
                writer.write(struct.pack(">HHHB", tid, 0, len(resp) + 1, unit) + resp)
                await writer.drain()
        except (asyncio.IncompleteReadError, ConnectionError):
            pass
        finally:
            writer.close()


class ClientTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.server = FakeModbusServer(LIVE_DUMP)
        self.port = await self.server.start()
        self.client = mc.ModbusTcpClient("127.0.0.1", self.port, 1, timeout=2.0)

    async def asyncTearDown(self) -> None:
        await self.client.close()
        await self.server.stop()

    async def test_read_all_blocks_and_decode(self) -> None:
        regs: dict[int, int] = {}
        for start, count in rg.REGISTER_BLOCKS:
            values = await self.client.read_holding_registers(start, count)
            regs |= {start + i: v for i, v in enumerate(values)}
        d = rg.decode_all(regs)
        self.assertEqual(d["vorlauf"], 39.65)
        self.assertEqual(d["cop_gesamt"], 4.58)

    async def test_undefined_address_raises_exception(self) -> None:
        with self.assertRaises(mc.ModbusExceptionResponse) as ctx:
            await self.client.read_holding_registers(1014, 1)
        self.assertEqual(ctx.exception.code, 2)
        # connection stays usable after an exception response
        self.assertEqual(await self.client.read_holding_registers(1004, 1), [3965])

    async def test_write_fc16_single_and_negative(self) -> None:
        await self.client.write_registers(1016, [-50])
        self.assertEqual(self.server.writes[-1], (1016, [65486]))
        await self.client.write_registers(1016, [370, 320, 50])
        self.assertEqual(self.server.writes[-1], (1016, [370, 320, 50]))

    async def test_reconnect_after_remote_disconnect(self) -> None:
        await self.server.stop()
        self.server = FakeModbusServer(LIVE_DUMP, close_after_first=True)
        self.port = await self.server.start()
        client = mc.ModbusTcpClient("127.0.0.1", self.port, 1, timeout=2.0)
        try:
            self.assertEqual(await client.read_holding_registers(1004, 1), [3965])
            # second request: server drops without answering -> reconnect + retry
            self.assertEqual(await client.read_holding_registers(1005, 1), [3631])
            self.assertEqual(self.server.connections, 2)
        finally:
            await client.close()

    async def test_connection_failure(self) -> None:
        client = mc.ModbusTcpClient("127.0.0.1", 1, 1, timeout=1.0)  # port 1: nothing
        with self.assertRaises(mc.ModbusConnectionError):
            await client.read_holding_registers(1000, 1)

    async def test_invalid_parameters(self) -> None:
        with self.assertRaises(ValueError):
            await self.client.read_holding_registers(0, 0)
        with self.assertRaises(ValueError):
            await self.client.read_holding_registers(0, 126)
        with self.assertRaises(ValueError):
            await self.client.write_registers(0, [])


class StartCounterTests(unittest.TestCase):
    """Counting rule against the Lambda status sequence (2026-11-13)."""

    # 5-minute polling; defrost cycles with restart, two real starts
    SEQUENCE: ClassVar[list[str]] = (
        ["Regelbetrieb"] * 3
        + ["Abtauung", "Verdichterstart", "Vorregelbetrieb"]  # restart after defrost
        + ["Regelbetrieb"] * 4
        + ["Abtauung", "Verdichterstart", "Regelbetrieb"]
        + ["Stopp"]
        + ["Sperrzeit"] * 4
        + ["Betriebsbereit"] * 20  # idle, hours
        + [
            "Pumpenstart",
            "Verdichterstart",
            "Vorregelbetrieb",
            "Regelbetrieb",
        ]  # start 1
        + ["Regelbetrieb"] * 5
        + ["Abtauung", "Verdichterstart", "Regelbetrieb"]
        + ["Stopp"]
        + ["Sperrzeit"] * 4
        + ["Betriebsbereit"] * 30
        + ["Verdichterstart", "Vorregelbetrieb", "Regelbetrieb"]  # start 2
        + ["Abtauung", "Verdichterstart", "Regelbetrieb"] * 2
    )

    def run_sequence(
        self, seq: list[str | None], counter: StartCounter | None = None
    ) -> StartCounter:
        c = counter or StartCounter()
        for status in seq:
            c.update(status)
        return c

    def test_only_start_from_idle_counts(self) -> None:
        # starting in running mode doesn't count; defrost restarts don't either
        self.assertEqual(self.run_sequence(list(self.SEQUENCE)).count, 2)

    def test_restart_while_running_does_not_count(self) -> None:
        self.assertEqual(self.run_sequence(["Regelbetrieb"]).count, 0)

    def test_idle_and_start_across_restore(self) -> None:
        c = self.run_sequence(["Stopp", "Sperrzeit"])
        c2 = StartCounter.from_dict(c.as_dict())  # HA restart during idle
        self.run_sequence(["Betriebsbereit", "Regelbetrieb"], c2)
        self.assertEqual(c2.count, 1)

    def test_unknown_and_outage_change_nothing(self) -> None:
        c = self.run_sequence(
            ["Sperrzeit", None, "Unbekannt", "Störung", "Regelbetrieb"]
        )
        self.assertEqual(c.count, 1)
        self.assertEqual(self.run_sequence([None, "Unbekannt"], c).count, 1)


class PollingTests(unittest.TestCase):
    INTERVALS: ClassVar[dict[str, int]] = {"fast": 30, "medium": 300, "slow": 900}

    def simulate(self, seconds: float, jitter: float = 0.0) -> dict[str, int]:
        last: dict[str, float] = {}
        reads = {"fast": 0, "medium": 0, "slow": 0}
        t = 0.0
        while t <= seconds:
            for g in polling.due_groups(t, last, self.INTERVALS, 30 * 0.25):
                last[g] = t
                reads[g] += 1
            t += 30 + jitter
        return reads

    def test_first_round_reads_all_groups(self) -> None:
        self.assertEqual(
            sorted(polling.due_groups(0.0, {}, self.INTERVALS)),
            ["fast", "medium", "slow"],
        )

    def test_read_frequency_per_hour(self) -> None:
        reads = self.simulate(3600 - 1)
        self.assertEqual(reads["fast"], 120)
        self.assertEqual(reads["medium"], 12)
        self.assertEqual(reads["slow"], 4)

    def test_scheduler_jitter_skips_no_group(self) -> None:
        reads = self.simulate(3600 - 1, jitter=0.8)
        self.assertGreaterEqual(reads["medium"], 11)
        self.assertGreaterEqual(reads["slow"], 3)

    def test_groups_cover_all_registers(self) -> None:
        groups = rg.REGISTER_GROUPS
        addresses = {
            a for blocks in groups.values() for s, c in blocks for a in range(s, s + c)
        }
        needed = {reg.address for reg in rg.REGISTERS}
        needed |= {reg.address + 1 for reg in rg.REGISTERS if reg.kind == rg.I32}
        self.assertTrue(needed <= addresses)
        self.assertNotIn(1014, addresses)
        flat = [
            a for blocks in groups.values() for s, c in blocks for a in range(s, s + c)
        ]
        self.assertEqual(len(flat), len(set(flat)))  # no duplicate polling


if __name__ == "__main__":
    unittest.main()
