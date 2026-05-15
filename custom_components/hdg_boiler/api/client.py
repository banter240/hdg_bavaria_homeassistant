"""API client for interacting with the HDG Bavaria Boiler web interface."""

from __future__ import annotations

__all__ = ["HdgApiClient"]

import functools
import time
from collections.abc import Awaitable, Callable
from typing import Any, Concatenate

import aiohttp
from aiohttp import ClientError

from ..const import (
    ACCEPTED_CONTENT_TYPES,
    API_ENDPOINT_DATA_REFRESH,
    API_ENDPOINT_SET_VALUE,
)
from ..exceptions import HdgApiConnectionError, HdgApiError, HdgApiResponseError
from ..helpers.logging_utils import _API_LOGGER, _LOGGER, format_for_log
from ..helpers.network_utils import prepare_base_url
from .protocols import HdgApiProtocol, ProtocolV1, ProtocolV2


def handle_api_errors[T, **P](
    func: Callable[Concatenate[HdgApiClient, P], Awaitable[T]],
) -> Callable[Concatenate[HdgApiClient, P], Awaitable[T]]:
    """Decorate API methods to handle common exceptions and re-raise as HdgApiErrors."""

    @functools.wraps(func)
    async def wrapper(self: HdgApiClient, *args: P.args, **kwargs: P.kwargs) -> T:
        """Wrap the API call with error handling."""
        start_time = time.monotonic()
        func_name = func.__name__
        try:
            return await func(self, *args, **kwargs)
        except (TimeoutError, ClientError) as err:
            duration = time.monotonic() - start_time
            _LOGGER.warning(
                "API Client: %s for %s after %.2fs. URL: %s. Error: %s",
                err.__class__.__name__,
                func_name,
                duration,
                self.base_url,
                err,
            )
            raise HdgApiConnectionError(
                f"Connection error during '{func_name}': {err}"
            ) from err
        except HdgApiError:
            raise  # Re-raise known API errors without modification
        except Exception as err:
            duration = time.monotonic() - start_time
            _LOGGER.exception(
                "API Client: Unexpected %s for %s after %.2fs. URL: %s. Error: %s",
                err.__class__.__name__,
                func_name,
                duration,
                self.base_url,
                err,
            )
            raise HdgApiError(f"Unexpected error in '{func_name}': {err}") from err

    return wrapper


class HdgApiClient:
    """Client to interact with the HDG Boiler API."""

    def __init__(
        self,
        session: aiohttp.ClientSession,
        host_address: str,
        api_timeout: float,
        connect_timeout: float,
    ) -> None:
        """Initialize the API client."""
        self._session = session
        self._aiohttp_timeout = aiohttp.ClientTimeout(
            total=api_timeout, connect=connect_timeout
        )
        _LOGGER.debug("HdgApiClient initialized with timeout: %s", api_timeout)

        prepared_base_url = prepare_base_url(host_address)
        if not prepared_base_url:
            raise HdgApiError(f"Invalid host_address provided: '{host_address}'")

        self._base_url = prepared_base_url
        self._url_data_refresh = f"{self._base_url}{API_ENDPOINT_DATA_REFRESH}"
        self._url_set_value_base = f"{self._base_url}{API_ENDPOINT_SET_VALUE}"

        self.protocol: HdgApiProtocol = ProtocolV2()
        self._protocol_auto_discovered = False

    @property
    def base_url(self) -> str:
        """Return the base URL of the HDG boiler API."""
        return self._base_url

    async def _parse_response(self, response: aiohttp.ClientResponse) -> Any:
        """Parse JSON response, handling content type and potential parsing errors.

        Args:
            response: The aiohttp.ClientResponse object.

        Returns:
            The parsed JSON data.

        Raises:
            HdgApiResponseError: If the content type is unexpected or JSON parsing fails.

        """
        content_type = response.headers.get("Content-Type", "").lower()

        if all(ct not in content_type for ct in ACCEPTED_CONTENT_TYPES):
            text = await response.text()
            _LOGGER.warning(
                "Unexpected Content-Type '%s'. Response: %s",
                content_type,
                format_for_log(text),
            )
            raise HdgApiResponseError(f"Unexpected Content-Type: {content_type}")

        try:
            return await response.json()
        except (aiohttp.ContentTypeError, ValueError) as err:
            text = await response.text()
            _LOGGER.warning(
                "Failed to parse JSON (Content-Type: '%s'): %s. Response: %s",
                content_type,
                err,
                format_for_log(text),
            )
            raise HdgApiResponseError(f"Failed to parse JSON: {err}") from err

    @handle_api_errors
    async def async_get_nodes_data(self, node_ids: list[str]) -> list[dict[str, Any]]:
        """Fetch data for a specified set of nodes from the HDG boiler.

        Args:
            node_ids: A list of node IDs for the data refresh.

        Returns:
            A list of dictionaries, where each dictionary represents a node's data.

        Raises:
            HdgApiResponseError: If the response is not a list of valid node dictionaries.

        """
        payload_str = self.protocol.generate_read_payload(node_ids)
        _API_LOGGER.debug(
            "Requesting data refresh (%s) with payload: %s",
            self.protocol.version_name,
            payload_str,
        )
        headers = {"Content-Type": "application/x-www-form-urlencoded; charset=UTF-8"}

        async with self._session.post(
            self._url_data_refresh,
            data=payload_str,
            headers=headers,
            timeout=self._aiohttp_timeout,
        ) as response:
            response.raise_for_status()
            json_response = await self._parse_response(response)

            # Auto-Discovery Fallback Logic
            if not self._protocol_auto_discovered and isinstance(json_response, dict):
                status = json_response.get("status")
                value = json_response.get("value")
                if status == "error" and value == "nodes is not an array":
                    # We are using ProtocolV2 on a ProtocolV1 boiler. Switch and retry.
                    _LOGGER.info(
                        "HDG Boiler reported 'nodes is not an array'. "
                        "Automatically switching to Legacy API Protocol (V1)."
                    )
                    self.protocol = ProtocolV1()
                    self._protocol_auto_discovered = True
                    return await self.async_get_nodes_data(node_ids)

            self._protocol_auto_discovered = True

            if not isinstance(json_response, list):
                raise HdgApiResponseError(
                    f"Expected list, got {type(json_response).__name__}"
                )

            return [
                item
                for item in json_response
                if isinstance(item, dict) and "id" in item and "text" in item
            ]

    @handle_api_errors
    async def async_set_node_value(self, node_id: str, value: str) -> bool:
        """Set a specific node value on the HDG boiler.

        Args:
            node_id: The ID of the node to update.
            value: The new value to set for the node.

        Returns:
            True if the operation was successful.

        Raises:
            HdgApiResponseError: If the API returns an error status or unexpected response.

        """
        _API_LOGGER.debug(
            "Setting node '%s' to value '%s' (%s)",
            node_id,
            value,
            self.protocol.version_name,
        )
        params = self.protocol.generate_write_params(node_id, value)

        async with self._session.get(
            self._url_set_value_base, params=params, timeout=self._aiohttp_timeout
        ) as response:
            response_text = await response.text()
            response.raise_for_status()  # Will raise ClientResponseError for 4xx/5xx

            _API_LOGGER.debug(
                "Successfully set node '%s'. Response: %s",
                node_id,
                format_for_log(response_text),
            )
            return True
