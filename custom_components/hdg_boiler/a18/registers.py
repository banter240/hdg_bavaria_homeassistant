"""HDG A18 register map and decoding (stdlib only).

Sources:
  * Lambda "MODBUS-PROTOKOLL Version 1.0" (2026) - the HDG A18 is a
    Lambda OEM device
  * Verified against a live register dump of the plant, 2026-11-13

Register address = index * 1000 + subindex * 100 + datapoint
  index 0 = general, 1 = heat pump (subindex 0 = first heat pump)

Deviations from the document are marked EMPIRICAL and checked on the
live system. Register 1014 is undefined in the document and never read.
"""

from __future__ import annotations

from dataclasses import dataclass
from collections.abc import Mapping
from typing import Any

I16, U16, I32 = "i16", "u16", "i32"

INT16_INVALID = 0x8000  # "no measurement" (e.g. source outlet on air-source)
INT32_INVALID = 0x80000000

UNKNOWN = "Unbekannt"

# Read ranges per poll group: (start, count). 1014 is undefined and never
# read. All ranges are defined in the document.
REGISTER_GROUPS: dict[str, tuple[tuple[int, int], ...]] = {
    # fast: temperatures, flow, compressor, power, COP, energy counters
    "fast": ((1004, 10), (1020, 4)),
    # medium: status, operating state, faults, request, heating element
    "medium": ((1000, 4), (1015, 5)),
    # slow: controller general (outside temperature, mode)
    "slow": ((0, 5),),
}

REGISTER_BLOCKS: tuple[tuple[int, int], ...] = tuple(
    block for blocks in REGISTER_GROUPS.values() for block in blocks
)

ENUMS: dict[str, dict[int, str]] = {
    "betriebsmodus_regler": {0: "Aus", 1: "Automatik", 2: "Manuell", 3: "Störung"},
    "fehlerzustand": {
        0: "Kein Fehler",
        1: "Meldung",
        2: "Warnung",
        3: "Fehler",
        4: "Störung",
    },
    "wp_status": {
        0: "Initialisierung",
        1: "Referenzierung",
        2: "Sperrzeit",
        3: "Betriebsbereit",
        4: "Pumpenstart",
        5: "Verdichterstart",
        6: "Vorregelbetrieb",
        7: "Regelbetrieb",
        8: "Nicht definiert",
        9: "Kühlen",
        10: "Abtauung",
        20: "Stopp",
        30: "Störung",
        31: "Fehler",
        40: "Fehler-Reset",
    },
    "betriebszustand": {
        0: "Standby",
        1: "Heizen",
        2: "Brauchwasser",
        3: "Kühlen",
        4: "Zirkulieren",
        5: "Abtauung",
        6: "Aus",
        7: "Frostschutz",
        8: "Betriebsbereit Frostschutz",
        9: "Nicht definiert",
        10: "Sommerbetrieb",
        11: "Ferienbetrieb",
        12: "Fehler",
        13: "Warnung",
        14: "Meldung",
        15: "Sperrzeit",
        16: "EVU-Sperre",
        17: "Temperatur-Sperre",
        18: "Software-Update",
    },
    # EMPIRICAL: document lists 1X14-1X18 as "undefined", but they deliver
    # the request issued by the HDG controller (enum like buffer request 3X05).
    "anf_typ": {-1: "Ungültig", 0: "Keine", 1: "Zirkulieren", 2: "Heizen", 3: "Kühlen"},
}


@dataclass(frozen=True, slots=True)
class Reg:
    """One Modbus register: key, address, kind (i16/u16/i32), divisor, enum."""

    key: str
    address: int
    kind: str  # I16 | U16 | I32
    div: int = 1  # divisor: 1, 10, 100
    enum: str | None = None


REGISTERS: tuple[Reg, ...] = (
    # --- Controller general (index 0, subindex 0)
    Reg("fehlernummer_regler", 0, I16),
    Reg("betriebsmodus_regler", 1, U16, enum="betriebsmodus_regler"),
    Reg("aussentemperatur", 2, I16, 10),
    Reg("aussentemperatur_1h", 3, I16, 10),
    Reg("aussentemperatur_berechnet", 4, I16, 10),
    # --- Heat pump 1 (index 1, subindex 0)
    Reg("fehlerzustand", 1000, U16, enum="fehlerzustand"),
    Reg("fehlernummer", 1001, I16),
    Reg("wp_status", 1002, U16, enum="wp_status"),
    Reg("betriebszustand", 1003, U16, enum="betriebszustand"),
    Reg("vorlauf", 1004, I16, 100),
    Reg("ruecklauf", 1005, I16, 100),
    # EMPIRICAL: document says 0.01 l/h; raw 1353 only fits at 1 l/h
    # (energy balance: 1353 l/h * 1.163 * 3.3 K = 5.2 kW, controller 4.9 kW)
    Reg("volumenstrom", 1006, I16),
    Reg("quelle_ein", 1007, I16, 100),
    Reg("quelle_aus", 1008, I16, 100),
    Reg("volumenstrom_quelle", 1009, I16),  # unit assumed like 1006, unverified
    Reg("verdichter", 1010, U16, 100),
    Reg("qp_heizen", 1011, I16, 10),
    Reg("leistung_el", 1012, I16),
    Reg("cop_geraet", 1013, I16, 100),  # EMPIRICAL: document "Wirkungsgrad [---]"
    # EMPIRICAL: 1015-1018 "undefined" per document
    Reg("anf_typ", 1015, I16, enum="anf_typ"),
    Reg("anf_vorlauf", 1016, I16, 10),
    Reg("anf_ruecklauf", 1017, I16, 10),
    Reg("anf_spreizung", 1018, I16, 10),
    Reg("heizstab", 1019, I16),
    Reg("energie_el_wh", 1020, I32),
    Reg("energie_th_wh", 1022, I32),
)


def enum_options(key: str) -> list[str]:
    """All states of an enum sensor including "Unbekannt"."""
    return [*ENUMS[key].values(), UNKNOWN]


def _signed(value: int, bits: int) -> int:
    return value - (1 << bits) if value >= 1 << (bits - 1) else value


def _raw_value(reg: Reg, regs: Mapping[int, int], int32_order: str) -> int | None:
    if reg.kind == I32:
        first, second = regs.get(reg.address), regs.get(reg.address + 1)
        if first is None or second is None:
            return None
        high, low = (second, first) if int32_order == "low_first" else (first, second)
        raw = (high << 16) | low
        return None if raw == INT32_INVALID else _signed(raw, 32)
    value = regs.get(reg.address)
    if value is None:
        return None
    if reg.kind == I16:
        return None if value == INT16_INVALID else _signed(value, 16)
    return value


def decode_all(
    regs: Mapping[int, int], int32_order: str = "low_first"
) -> dict[str, Any]:
    """Convert raw registers to values and compute derived quantities.

    Missing or invalid registers yield None.
    """
    raws: dict[str, int | None] = {}
    out: dict[str, Any] = {}
    for reg in REGISTERS:
        raw = _raw_value(reg, regs, int32_order)
        raws[reg.key] = raw
        if raw is None:
            out[reg.key] = None
        elif reg.enum:
            out[reg.key] = ENUMS[reg.enum].get(raw, UNKNOWN)
        elif reg.div == 1:
            out[reg.key] = raw
        else:
            out[reg.key] = round(raw / reg.div, len(str(reg.div)) - 1)

    el, th = raws["energie_el_wh"], raws["energie_th_wh"]
    out["energie_el_kwh"] = None if el is None else round(el / 1000, 3)
    out["energie_th_kwh"] = None if th is None else round(th / 1000, 3)
    out["cop_gesamt"] = round(th / el, 2) if el and th is not None and el > 0 else None

    vl, rl = out["vorlauf"], out["ruecklauf"]
    out["spreizung"] = None if vl is None or rl is None else round(vl - rl, 2)

    out["heizstab_relais"] = (
        None if raws["heizstab"] is None else bool(raws["heizstab"])
    )
    out["verdichter_laeuft"] = (
        None if raws["verdichter"] is None else raws["verdichter"] > 0
    )
    out["stoerung"] = (
        None if raws["fehlerzustand"] is None else raws["fehlerzustand"] in (3, 4)
    )
    if raws["wp_status"] is None and raws["betriebszustand"] is None:
        out["abtauung"] = None
    else:
        out["abtauung"] = raws["wp_status"] == 10 or raws["betriebszustand"] == 5
    return out
