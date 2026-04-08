"""API client for interacting with the HDG Bavaria Boiler web interface."""

from __future__ import annotations

__version__ = "0.3.0"
__all__ = ["HdgApiClient"]

import functools
import re
import time
from collections.abc import Awaitable, Callable
from typing import Any, Concatenate

import aiohttp
from aiohttp import ClientError

from .const import (
    ACCEPTED_CONTENT_TYPES,
    API_ENDPOINT_DATA_REFRESH,
    API_ENDPOINT_SET_VALUE,
    DATA_REFRESH_PAYLOAD_MODE_AUTO,
    DATA_REFRESH_PAYLOAD_MODE_INDEXED,
    DATA_REFRESH_PAYLOAD_MODE_LEGACY,
    DATA_REFRESH_PAYLOAD_MODES,
    DEFAULT_DATA_REFRESH_PAYLOAD_MODE,
)
from .exceptions import HdgApiConnectionError, HdgApiError, HdgApiResponseError
from .helpers.logging_utils import _API_LOGGER, _LOGGER, format_for_log
from .helpers.network_utils import prepare_base_url


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
        data_refresh_payload_mode: str = DEFAULT_DATA_REFRESH_PAYLOAD_MODE,
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
        self._data_refresh_payload_mode = self._normalize_payload_mode(
            data_refresh_payload_mode
        )
        self._detected_data_refresh_mode: str | None = None
        self._fw_based_preferred_mode: str | None = None

    @staticmethod
    def _normalize_payload_mode(mode: str) -> str:
        """Normalize payload mode and fallback to default when invalid."""
        if mode in DATA_REFRESH_PAYLOAD_MODES:
            return mode
        _LOGGER.warning(
            "Unknown data refresh payload mode '%s'. Falling back to '%s'.",
            mode,
            DEFAULT_DATA_REFRESH_PAYLOAD_MODE,
        )
        return DEFAULT_DATA_REFRESH_PAYLOAD_MODE

    @staticmethod
    def _extract_node_ids_from_legacy_payload(node_payload_str: str) -> list[str]:
        """Extract canonical node IDs from legacy 'nodes=...T' payload."""
        match = re.match(r"^nodes=(.+)$", node_payload_str)
        if not match:
            return []
        payload_body = match.group(1)
        node_ids = [
            token[:-1] if token.endswith("T") else token
            for token in payload_body.split("-")
            if token
        ]
        return [node_id for node_id in node_ids if node_id.isdigit()]

    @staticmethod
    def _build_indexed_payload(node_ids: list[str]) -> dict[str, str]:
        """Build structured form payload for dataRefresh."""
        payload: dict[str, str] = {}
        for idx, node_id in enumerate(node_ids):
            payload[f"nodes[{idx}][id]"] = node_id
            payload[f"nodes[{idx}][type]"] = "text"
        return payload

    def _build_data_refresh_payload_candidates(
        self, node_payload_str: str
    ) -> list[tuple[str, str | dict[str, str]]]:
        """Build payload candidates in order, based on configured mode."""
        node_ids = self._extract_node_ids_from_legacy_payload(node_payload_str)
        indexed_payload = self._build_indexed_payload(node_ids) if node_ids else None
        legacy_candidate = (DATA_REFRESH_PAYLOAD_MODE_LEGACY, node_payload_str)
        indexed_candidate = (
            DATA_REFRESH_PAYLOAD_MODE_INDEXED,
            indexed_payload,
        )

        if self._data_refresh_payload_mode == DATA_REFRESH_PAYLOAD_MODE_LEGACY:
            return [legacy_candidate]
        if self._data_refresh_payload_mode == DATA_REFRESH_PAYLOAD_MODE_INDEXED:
            return [indexed_candidate] if indexed_payload else [legacy_candidate]

        if self._fw_based_preferred_mode == DATA_REFRESH_PAYLOAD_MODE_INDEXED:
            if indexed_payload:
                return [indexed_candidate, legacy_candidate]
            return [legacy_candidate]
        if self._fw_based_preferred_mode == DATA_REFRESH_PAYLOAD_MODE_LEGACY:
            return [legacy_candidate] + ([indexed_candidate] if indexed_payload else [])

        if self._detected_data_refresh_mode == DATA_REFRESH_PAYLOAD_MODE_INDEXED:
            if indexed_payload:
                return [indexed_candidate, legacy_candidate]
            return [legacy_candidate]
        if self._detected_data_refresh_mode == DATA_REFRESH_PAYLOAD_MODE_LEGACY:
            return [legacy_candidate] + ([indexed_candidate] if indexed_payload else [])

        # Auto mode: try legacy first for backward compatibility, then indexed.
        return [legacy_candidate] + ([indexed_candidate] if indexed_payload else [])

    @staticmethod
    def _parse_touch_fw_version(value: Any) -> tuple[int, ...] | None:
        """Parse software version strings like '1.54' into a comparable tuple."""
        if not isinstance(value, str):
            return None
        # Keep only numeric parts (e.g. 1.54, 1.54.2, 1.54 beta).
        version_match = re.search(r"\d+(?:\.\d+)+", value.strip())
        if not version_match:
            return None
        try:
            return tuple(int(part) for part in version_match.group(0).split("."))
        except ValueError:
            return None

    def _apply_auto_fw_heuristics(self, items: list[dict[str, Any]]) -> None:
        """Apply known firmware compatibility heuristics for auto payload mode.

        For Touch firmware <= 1.54, field reports indicate indexed form payload is
        required for dataRefresh. We only apply this in auto mode.
        """
        if self._data_refresh_payload_mode != DATA_REFRESH_PAYLOAD_MODE_AUTO:
            return

        touch_item = next((item for item in items if str(item.get("id")) == "20003"), None)
        if touch_item is None:
            return

        version_tuple = self._parse_touch_fw_version(touch_item.get("text"))
        if version_tuple is None:
            return

        if version_tuple <= (1, 54):
            if self._fw_based_preferred_mode != DATA_REFRESH_PAYLOAD_MODE_INDEXED:
                _API_LOGGER.info(
                    "Detected Touch firmware <= 1.54 (%s). Preferring '%s' dataRefresh payload mode in auto.",
                    touch_item.get("text"),
                    DATA_REFRESH_PAYLOAD_MODE_INDEXED,
                )
            self._fw_based_preferred_mode = DATA_REFRESH_PAYLOAD_MODE_INDEXED
        else:
            self._fw_based_preferred_mode = DATA_REFRESH_PAYLOAD_MODE_LEGACY

    @property
    def base_url(self) -> str:
        """Return the base URL of the HDG boiler API."""
        return self._base_url

    @property
    def data_refresh_payload_mode(self) -> str:
        """Return configured payload mode for dataRefresh."""
        return self._data_refresh_payload_mode

    @property
    def detected_data_refresh_payload_mode(self) -> str | None:
        """Return auto-detected payload mode if available."""
        return self._detected_data_refresh_mode

    @property
    def effective_data_refresh_payload_mode(self) -> str:
        """Return currently effective payload mode for dataRefresh."""
        if self._data_refresh_payload_mode != DATA_REFRESH_PAYLOAD_MODE_AUTO:
            return self._data_refresh_payload_mode
        return (
            self._fw_based_preferred_mode
            or self._detected_data_refresh_mode
            or DATA_REFRESH_PAYLOAD_MODE_AUTO
        )

    @property
    def firmware_based_preferred_payload_mode(self) -> str | None:
        """Return payload mode selected by firmware heuristic, if any."""
        return self._fw_based_preferred_mode

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
    async def async_get_nodes_data(self, node_payload_str: str) -> list[dict[str, Any]]:
        """Fetch data for a specified set of nodes from the HDG boiler.

        Args:
            node_payload_str: A string containing the node IDs for the data refresh.

        Returns:
            A list of dictionaries, where each dictionary represents a node's data.

        Raises:
            HdgApiResponseError: If the response is not a list of valid node dictionaries.

        """
        _API_LOGGER.debug("Requesting data refresh with payload: %s", node_payload_str)
        headers = {"Content-Type": "application/x-www-form-urlencoded; charset=UTF-8"}
        candidates = self._build_data_refresh_payload_candidates(node_payload_str)
        last_error: Exception | None = None

        for idx, (mode, payload) in enumerate(candidates):
            if payload is None:
                continue

            try:
                async with self._session.post(
                    self._url_data_refresh,
                    data=payload,
                    headers=headers,
                    timeout=self._aiohttp_timeout,
                ) as response:
                    response.raise_for_status()
                    json_response = await self._parse_response(response)

                    if not isinstance(json_response, list):
                        raise HdgApiResponseError(
                            f"Expected list, got {type(json_response).__name__}"
                        )

                    # Filter for valid node data to ensure integrity
                    filtered_items = [
                        item
                        for item in json_response
                        if isinstance(item, dict) and "id" in item and "text" in item
                    ]
                    has_fallback_candidate = idx < (len(candidates) - 1)
                    if (
                        self._data_refresh_payload_mode == DATA_REFRESH_PAYLOAD_MODE_AUTO
                        and not filtered_items
                        and has_fallback_candidate
                    ):
                        _API_LOGGER.debug(
                            "dataRefresh returned empty list with mode '%s'; trying fallback mode.",
                            mode,
                        )
                        continue

                    if self._data_refresh_payload_mode == DATA_REFRESH_PAYLOAD_MODE_AUTO:
                        self._detected_data_refresh_mode = mode

                    self._apply_auto_fw_heuristics(filtered_items)
                    return filtered_items
            except (aiohttp.ClientResponseError, HdgApiResponseError) as err:
                last_error = err
                _API_LOGGER.debug(
                    "dataRefresh request failed with mode '%s', trying next if available. Error: %s",
                    mode,
                    err,
                )
                continue

        if last_error:
            raise last_error
        raise HdgApiResponseError("No valid dataRefresh payload candidate available.")

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
        _API_LOGGER.debug("Setting node '%s' to value '%s'", node_id, value)
        params = {"i": node_id, "v": value}

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
