"""Tests for the WebControl wire formats (V2 and V1 payloads).

Stdlib unittest only - run with:
    ../.venv/bin/python -m pytest tests/ -q

protocols.py is pure stdlib, but its package __init__ pulls the whole
integration (HA imports), so the module is loaded directly from its
file instead of through the package machinery.
"""

from __future__ import annotations

import importlib.util
import unittest
from pathlib import Path

_PROTOCOLS_PATH = (
    Path(__file__).resolve().parents[1]
    / "custom_components"
    / "hdg_boiler"
    / "api"
    / "protocols.py"
)
_spec = importlib.util.spec_from_file_location("hdg_protocols", _PROTOCOLS_PATH)
assert _spec is not None and _spec.loader is not None
protocols = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(protocols)


class TestProtocolV2(unittest.TestCase):
    def test_read_payload_joins_with_t_suffix(self) -> None:
        self.assertEqual(
            protocols.ProtocolV2().generate_read_payload(["24000T", "24001T"]),
            "nodes=24000T-24001T",
        )

    def test_read_payload_strips_inner_t_only(self) -> None:
        # Payload ids carry one leading and one trailing T; inner Ts survive.
        self.assertEqual(
            protocols.ProtocolV2().generate_read_payload(["20026T"]),
            "nodes=20026T",
        )

    def test_empty_node_list(self) -> None:
        self.assertEqual(protocols.ProtocolV2().generate_read_payload([]), "nodes=")

    def test_write_params(self) -> None:
        self.assertEqual(
            protocols.ProtocolV2().generate_write_params("15001T", "21.5"),
            {"i": "15001T", "v": "21.5"},
        )

    def test_version_name(self) -> None:
        self.assertEqual(protocols.ProtocolV2().version_name, "V2 (Modern)")


class TestProtocolV1(unittest.TestCase):
    def test_read_payload_legacy_encoding(self) -> None:
        self.assertEqual(
            protocols.ProtocolV1().generate_read_payload(["24000T", "24001T"]),
            "nodes%5B0%5D%5Bid%5D=24000"
            "&nodes%5B0%5D%5Btype%5D=text"
            "&nodes%5B1%5D%5Bid%5D=24001"
            "&nodes%5B1%5D%5Btype%5D=text",
        )

    def test_read_payload_empty(self) -> None:
        self.assertEqual(protocols.ProtocolV1().generate_read_payload([]), "")

    def test_write_params_match_v2_shape(self) -> None:
        self.assertEqual(
            protocols.ProtocolV1().generate_write_params("24000T", "1"),
            {"i": "24000T", "v": "1"},
        )


class TestTrailingT(unittest.TestCase):
    def test_strip_removes_single_t(self) -> None:
        self.assertEqual(
            protocols.HdgApiProtocol._strip_trailing_t(None, "24000T"), "24000"
        )

    def test_strip_keeps_plain_id(self) -> None:
        self.assertEqual(
            protocols.HdgApiProtocol._strip_trailing_t(None, "24000"), "24000"
        )


if __name__ == "__main__":
    unittest.main()
