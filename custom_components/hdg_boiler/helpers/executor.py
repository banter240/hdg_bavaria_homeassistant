"""Executes HdgCommand objects against the HDG Boiler API.

This module provides a decoupled executor for processing queued API commands,
following the Command Pattern to separate queue management from API invocation.
"""

from __future__ import annotations

from typing import Any

from ..api.client import HdgApiClient
from ..models import CommandType, HdgCommand


class HdgCommandExecutor:
    """Executes unified API commands."""

    def __init__(self, api_client: HdgApiClient) -> None:
        """Initialize the command executor."""
        self._api_client = api_client

    async def execute(self, command: HdgCommand) -> Any:
        """Execute a single API command and return the result."""
        if command.cmd_type == CommandType.GET_NODES:
            if not command.node_ids:
                raise ValueError("GET_NODES command requires 'node_ids'.")
            return await self._api_client.async_get_nodes_data(command.node_ids)

        if command.cmd_type == CommandType.SET_NODE:
            if command.node_id is None or command.value is None:
                raise ValueError("SET_NODE command requires 'node_id' and 'value'.")
            return await self._api_client.async_set_node_value(
                command.node_id, command.value
            )

        raise ValueError(f"Unknown command type: {command.cmd_type}")
