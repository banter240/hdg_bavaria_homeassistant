"""
API client for interacting with the HDG Bavaria Boiler web interface.

This module provides the `HdgApiClient` class for HTTP communication
with the HDG Bavaria boiler's web API. It handles request formatting,
response parsing, error management, and offers methods for fetching
data and setting values.
"""

__version__ = "0.8.25"

import asyncio
import logging
from typing import Any, Dict, List
from urllib.parse import urlparse, urlunparse, urlencode, parse_qsl

import aiohttp
import async_timeout

from .utils import (
    normalize_host_for_scheme,
)

from .const import API_ENDPOINT_DATA_REFRESH, API_ENDPOINT_SET_VALUE, DOMAIN, API_TIMEOUT

_LOGGER = logging.getLogger(DOMAIN)


class HdgApiError(Exception):
    """Base exception for all HDG API client errors."""

    pass


class HdgApiConnectionError(HdgApiError):
    """Raised when there's an issue connecting to the HDG API (e.g., timeout, network error)."""

    pass


class HdgApiResponseError(HdgApiError):
    """Raised when the HDG API returns an unexpected or error response (e.g., non-JSON, bad status code)."""

    pass


class HdgApiClient:
    """
    Client to interact with the HDG Boiler API.

    Handles HTTP communication, request formatting, response parsing, and error
    management for fetching data from and setting values on the HDG boiler.
    """

    def __init__(self, session: aiohttp.ClientSession, host_address: str) -> None:
        """
        Initialize the API client.

        Args:
            session: An `aiohttp.ClientSession` instance for making HTTP requests.
            host_address: The host address (IP or hostname) of the HDG boiler.
                          The client will ensure this address is prefixed with 'http://'
                          if no scheme is provided.

        Raises:
            HdgApiError: If the `host_address` is invalid (e.g., results in an empty netloc).
        """
        self._session = session
        host_address_stripped = host_address.strip()
        if not host_address_stripped:
            _LOGGER.error("Provided host_address is empty after stripping whitespace.")
            raise HdgApiError("host_address must not be empty or whitespace only.")

        if not host_address_stripped.lower().startswith(("http://", "https://")):
            temp_host_for_scheme = host_address_stripped
            normalized_host_part = normalize_host_for_scheme(temp_host_for_scheme)
            schemed_host_input = f"http://{normalized_host_part}"
        else:
            schemed_host_input = host_address_stripped

        parsed_url = urlparse(schemed_host_input)
        # Ensure that urlparse successfully extracted a network location (netloc).
        # An empty netloc typically means the input host_address was fundamentally invalid.
        if not parsed_url.netloc:  # pragma: no cover
            _LOGGER.error(
                f"Invalid host_address '{host_address_stripped}' for API client. "
                f"Expected a valid hostname or IP address, optionally with a port (e.g., '192.168.1.100', 'example.com:8080', '[fe80::1]:8080'). "
                f"Input after scheme/IPv6 normalization: '{schemed_host_input}', Parsed URL: {parsed_url}. "
                f"Please check your configuration and ensure the host_address is in the correct format."
            )
            raise HdgApiError(
                f"Invalid host_address for API client: '{host_address}'. "
                f"Expected a valid hostname or IP address, optionally with a port (e.g., '192.168.1.100', 'example.com:8080', '[fe80::1]:8080'). "
                f"Please check your configuration."
            )

        self._base_url = urlunparse((parsed_url.scheme, parsed_url.netloc, "", "", "", ""))
        self._url_data_refresh = f"{self._base_url}{API_ENDPOINT_DATA_REFRESH}"
        self._url_set_value_base = f"{self._base_url}{API_ENDPOINT_SET_VALUE}"

    @property
    def base_url(self) -> str:
        """Return the base URL of the HDG boiler API."""
        return self._base_url

    async def _async_handle_data_refresh_response(
        self, response: aiohttp.ClientResponse, node_payload_str: str
    ) -> List[Dict[str, Any]]:  # sourcery skip: invert-any-all
        """
        Handle and parse the response from the dataRefresh API endpoint.

        Args:
            response: The aiohttp.ClientResponse object.
            node_payload_str: The original payload string, for logging context.

        Returns:
            A list of node data dictionaries.

        Raises:
            HdgApiResponseError: If the response is malformed, has an unexpected
                                 status code, or an unexpected content type.
            aiohttp.ClientResponseError: If response.raise_for_status() detects an HTTP error.
        """
        response.raise_for_status()

        content_type_header = response.headers.get("Content-Type", "").lower()
        # Normalize content_type by stripping parameters (e.g., charset)
        content_type_main = content_type_header.split(";")[0].strip()

        if content_type_main == "text/plain":  # Exact match for plain text
            _LOGGER.warning(
                f"Accepting 'text/plain' as JSON response for dataRefresh (payload: {node_payload_str}). "
                "This may mask unexpected server responses or misconfigurations."
            )

        if not any(
            accepted_type in content_type_header
            for accepted_type in ("application/json", "text/json", "text/plain")
        ):
            text_response = await response.text()
            if "text/html" in content_type_header:  # Common indicator of an error page
                _LOGGER.warning(
                    f"Received HTML response from HDG API for dataRefresh (payload: {node_payload_str}). "
                    f"Content-Type: {content_type_header}, Content (truncated): {text_response[:200]}"
                )
                raise HdgApiResponseError(
                    f"Received HTML error page from HDG API. Content (truncated): {text_response[:100]}"
                )
            else:
                _LOGGER.warning(
                    f"Unexpected Content-Type '{content_type_header}' for dataRefresh (payload: {node_payload_str}). "
                    f"Response text: {text_response[:200]}..."
                )
                raise HdgApiResponseError(
                    f"Unexpected Content-Type for dataRefresh: {content_type_header}"
                )

        try:
            json_response = await response.json()
        except (aiohttp.ContentTypeError, ValueError) as err:  # ValueError for json.JSONDecodeError
            text_response_for_error = await response.text()
            _LOGGER.warning(
                f"Failed to parse JSON response for dataRefresh (payload: {node_payload_str}) "
                f"despite Content-Type '{content_type_header}'. Error: {err}. Response: {text_response_for_error[:200]}..."
            )
            raise HdgApiResponseError(
                f"Failed to parse JSON response (Content-Type: {content_type_header}, Error: {err}): {text_response_for_error[:100]}"
            ) from err

        if not isinstance(json_response, list):
            _LOGGER.error(
                f"API response for dataRefresh (payload: {node_payload_str}) was not a list: {str(json_response)[:200]}"
            )
            raise HdgApiResponseError(
                f"Unexpected API response type for dataRefresh (not a list): {type(json_response)}"
            )

        valid_items: List[Dict[str, Any]] = []
        malformed_item_indices: List[int] = []

        for idx, item in enumerate(json_response):
            if not isinstance(item, dict):
                _LOGGER.warning(
                    f"Item at index {idx} in dataRefresh response (payload: {node_payload_str}) is not a dict: {item!r}. Skipping."
                )
                malformed_item_indices.append(idx)
                continue

            if missing_fields := [field for field in ("id", "text") if field not in item]:
                _LOGGER.warning(
                    f"Item at index {idx} in dataRefresh response (payload: {node_payload_str}) is missing required fields {missing_fields}: {item!r}. Skipping."
                )
                malformed_item_indices.append(idx)
                continue

            if unexpected_fields := set(item.keys()) - {"id", "text"}:
                _LOGGER.info(  # Log unexpected fields; usually not critical.
                    f"Item at index {idx} in dataRefresh response (payload: {node_payload_str}) "
                    f"has unexpected fields {unexpected_fields}: {item!r}"
                )
            valid_items.append(item)

        _LOGGER.debug(
            f"Successfully parsed {len(valid_items)} valid nodes from dataRefresh response (payload: {node_payload_str}). "
            f"{len(malformed_item_indices)} items were skipped due to malformation or missing required fields."
        )
        return valid_items

    async def async_get_nodes_data(self, node_payload_str: str) -> List[Dict[str, Any]]:
        """
        Fetch data for a specified set of nodes from the HDG boiler.

        The HDG API expects a POST request with node IDs in a specific format
        (e.g., "nodes=ID1T-ID2T-ID3T") to the `API_ENDPOINT_DATA_REFRESH` endpoint.
        A successful response is typically a JSON list of dictionaries, where each
        dictionary contains an 'id' (the API node ID, often with a 'T' suffix)
        and a 'text' (the raw string value of the node).

        Args:
            node_payload_str: The payload string for the POST request,
                              formatted as "nodes=ID1T-ID2T-..."

        Returns:
            A list of node data dictionaries upon successful API interaction.
            An empty list is considered a valid successful response, for instance,
            if the API returns no data for the requested nodes or if an empty
            payload string was sent.

        Raises:
            HdgApiConnectionError: If there's a connection issue (e.g., timeout, network error).
            HdgApiResponseError: If the API response is malformed, has an unexpected
                                 status code, or an unexpected content type.
            HdgApiError: For other unexpected API-related errors during the process.
        """
        _LOGGER.debug(
            f"Requesting data refresh. URL: {self._url_data_refresh}, Payload: {node_payload_str}"
        )

        headers = {"Content-Type": "application/x-www-form-urlencoded; charset=UTF-8"}
        try:
            async with async_timeout.timeout(API_TIMEOUT):
                async with self._session.post(
                    self._url_data_refresh, data=node_payload_str, headers=headers
                ) as response:
                    return await self._async_handle_data_refresh_response(
                        response, node_payload_str
                    )
        except asyncio.TimeoutError as err:
            _LOGGER.error(
                f"Timeout connecting to HDG API at {self._url_data_refresh} for dataRefresh (payload: {node_payload_str}): {err}"
            )
            raise HdgApiConnectionError(f"Timeout during dataRefresh: {err}") from err
        except aiohttp.ClientError as err:
            # Handles various client-side connection errors and HTTP 4xx/5xx errors via response.raise_for_status().
            _LOGGER.error(
                f"Client error during dataRefresh to {self._url_data_refresh} (payload: {node_payload_str}): {err}"
            )
            raise HdgApiConnectionError(f"Client error during dataRefresh: {err}") from err
        except HdgApiError:
            raise
        except Exception as err:
            if isinstance(err, (KeyboardInterrupt, SystemExit)):
                raise  # pragma: no cover
            _LOGGER.exception(  # Use .exception to include traceback automatically
                f"Unexpected error during dataRefresh to {self._url_data_refresh} (payload: {node_payload_str}): {err}",
            )
            raise  # Re-raise the original (non-system-exiting) exception

    async def async_set_node_value(self, node_id: str, value: str) -> bool:
        """
        Set a specific node value on the HDG boiler.

        The HDG API for setting values uses a GET request with parameters in the URL
        (e.g., `/ActionManager.php?action=set_value_changed&i=NODE_ID&v=VALUE`).
        A successful operation is typically indicated by an HTTP 200 status code
        in the response. The response body is often minimal (e.g., "OK") or empty.

        Args:
            node_id: The node ID to set (e.g., "6024"). This should be the base ID
                     without API-specific suffixes like 'T', 'U', etc.
            value: The value to set for the node, as a string.

        Returns:
            True if the value was successfully set (HTTP 200), False otherwise.

        Raises:
            HdgApiConnectionError: If there's a connection issue (timeout, network error).
            HdgApiError: For other unexpected API-related errors during the set operation.
        """
        base_url_parts = urlparse(self._url_set_value_base)
        existing_query_list = parse_qsl(base_url_parts.query, keep_blank_values=True)
        existing_query_dict = dict(existing_query_list) | {"i": node_id, "v": value}
        new_query_string = urlencode(existing_query_dict)

        url_with_params = urlunparse(base_url_parts._replace(query=new_query_string))
        _LOGGER.debug(f"Setting node '{node_id}' to '{value}' via GET: {url_with_params}")
        try:
            async with async_timeout.timeout(API_TIMEOUT):
                async with self._session.get(url_with_params) as response:
                    response_text = await response.text()
                    if response.status == 200:
                        # The HDG API usually returns a simple text response (e.g., "OK") or an empty body on success.
                        _LOGGER.debug(
                            f"Successfully set node '{node_id}' to '{value}'. Response status: {response.status}, Text: {response_text[:100]}"
                        )
                        return True
                    else:
                        # Non-200 status indicates failure.
                        _LOGGER.error(
                            f"Failed to set HDG node '{node_id}'. Status: {response.status}. Response: {response_text[:200]}"
                        )
                        return False
        except asyncio.TimeoutError as err:
            _LOGGER.error(
                f"Timeout connecting to HDG API at {url_with_params} for set_node_value: {err}"
            )
            raise HdgApiConnectionError(f"Timeout during set_node_value: {err}") from err
        except aiohttp.ClientError as err:
            _LOGGER.error(f"Client error during set_node_value to {url_with_params}: {err}")
            raise HdgApiConnectionError(f"Client error during set_node_value: {err}") from err
        except Exception as err:
            _LOGGER.exception(f"Unexpected error during set_node_value to {url_with_params}: {err}")
            raise HdgApiError(f"Unexpected error during set_node_value: {err}") from err

    async def async_check_connectivity(self) -> bool:
        """
        Perform a basic connectivity test to the HDG boiler API.

        This method attempts to fetch a small, predefined set of static nodes
        (e.g., language, boiler type) to verify that the API is reachable and
        responding correctly. It's a lightweight way to check if the configured
        host is an HDG boiler and is operational, without fetching all data groups.

        Returns:
            True if the connectivity test is successful (API responds as expected).
            False if any HdgApiError occurs during the test, indicating a problem.
        """  # Minimal payload to check API responsiveness.
        connectivity_test_payload_str = "nodes=1-2-3T"
        _LOGGER.debug(
            f"Performing connectivity test to {self._base_url} with payload: {connectivity_test_payload_str}"
        )
        try:
            data = await self.async_get_nodes_data(connectivity_test_payload_str)
            # Success if a list is returned (even empty), indicating no critical API errors.
            return isinstance(data, list)
        except HdgApiError:
            # Any HdgApiError during this minimal fetch indicates a connectivity problem.
            return False
