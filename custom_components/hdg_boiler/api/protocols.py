"""HDG Boiler API Protocols.

This module defines the different payload generation protocols for different
firmware versions of the HDG Bavaria Boiler WebControl interface.
"""

from __future__ import annotations

import abc


class HdgApiProtocol(abc.ABC):
    """Abstract base class for HDG Boiler API protocols."""

    @property
    @abc.abstractmethod
    def version_name(self) -> str:
        """Return the name of the protocol version."""

    @abc.abstractmethod
    def generate_read_payload(self, node_ids: list[str]) -> str:
        """Generate the HTTP POST body payload for reading node data."""

    @abc.abstractmethod
    def generate_write_params(self, node_id: str, value: str) -> dict[str, str]:
        """Generate the HTTP GET query parameters for writing a node value."""

    def _strip_trailing_t(self, node_id: str) -> str:
        """Strip the 'T' suffix from node IDs if present."""
        return node_id[:-1] if node_id.endswith("T") else node_id


class ProtocolV2(HdgApiProtocol):
    """Modern protocol used by newer HDG WebControl versions.

    Payload format: nodes=20000T-24000T-24001T
    """

    @property
    def version_name(self) -> str:
        """Return the name of the protocol version."""
        return "V2 (Modern)"

    def generate_read_payload(self, node_ids: list[str]) -> str:
        """Generate the payload string for a given list of node IDs."""
        if not node_ids:
            return "nodes="
        payload_base_ids = [self._strip_trailing_t(nid) for nid in node_ids]
        return f"nodes={'T-'.join(payload_base_ids)}T"

    def generate_write_params(self, node_id: str, value: str) -> dict[str, str]:
        """Generate write parameters. V2 uses 'i' for ID and 'v' for value."""
        return {"i": node_id, "v": value}


class ProtocolV1(HdgApiProtocol):
    """Legacy protocol used by older HDG WebControl versions.

    Payload format: nodes[0][id]=24000&nodes[0][type]=text&nodes[1][id]=24001...
    """

    @property
    def version_name(self) -> str:
        """Return the name of the protocol version."""
        return "V1 (Legacy)"

    def generate_read_payload(self, node_ids: list[str]) -> str:
        """Generate the legacy URL-encoded payload string."""
        parts: list[str] = []
        for index, nid in enumerate(node_ids):
            base_id = self._strip_trailing_t(nid)
            parts.extend(
                (
                    f"nodes%5B{index}%5D%5Bid%5D={base_id}",
                    f"nodes%5B{index}%5D%5Btype%5D=text",
                )
            )
        return "&".join(parts)

    def generate_write_params(self, node_id: str, value: str) -> dict[str, str]:
        """Generate write parameters.

        V1 likely uses the same 'i' and 'v' logic, but we abstract it here
        in case it differs later.
        """
        return {"i": node_id, "v": value}
