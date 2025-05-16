"""
API client for interacting with the HDG Bavaria Boiler web interface.

This module provides the HdgApiClient class, which encapsulates the logic
for sending requests to the HDG boiler's web API, handling responses,
and managing potential errors during communication. It interacts with
endpoints for refreshing data and setting node values.
"""

__version__ = "0.7.0"

import asyncio
import logging
from typing import Any, Dict, List

import aiohttp
import async_timeout

from .const import API_ENDPOINT_DATA_REFRESH, API_ENDPOINT_SET_VALUE, DOMAIN

_LOGGER = logging.getLogger(DOMAIN)

DEFAULT_TIMEOUT = 15  # Seconds for API requests


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
    """Client to interact with the HDG Boiler API."""

    def __init__(self, session: aiohttp.ClientSession, host_address: str) -> None:
        """
        Initialize the API client.

        Args:
            session: The aiohttp client session to use for requests.
            host_address: The host address (IP or hostname) of the HDG boiler.
                          The 'http://' schema will be added if not present.
        """
        self._session = session
        # Ensure the base_url starts with http:// for proper request formation.
        if not host_address.startswith(("http://", "https://")):
            processed_url = f"http://{host_address}"
        else:
            processed_url = (
                host_address  # pragma: no cover # Defensive: user might provide full URL
            )
        # Ensure no trailing slash for consistent URL construction with API endpoints.
        self._base_url = processed_url.rstrip("/")
        self._url_data_refresh = f"{self._base_url}{API_ENDPOINT_DATA_REFRESH}"
        self._url_set_value_base = f"{self._base_url}{API_ENDPOINT_SET_VALUE}"

    async def async_get_nodes_data(self, node_payload_str: str) -> List[Dict[str, Any]]:
        """
        Fetch data for a specified set of nodes from the HDG boiler.

        The HDG API expects a POST request with node IDs in a specific format
        (e.g., "nodes=ID1T-ID2T-ID3T"). It typically returns a JSON list of
        dictionaries, where each dictionary represents a node with its 'id'
        (the API node ID, possibly with a suffix) and 'text' (the raw string value).

        Args:
            node_payload_str: The payload string identifying the nodes to fetch.

        Returns:
            A list of node data dictionaries upon successful API interaction.
            An empty list is a valid successful response (e.g., if the API returns
            no data for the requested nodes or if an empty payload was sent).

        Raises:
            HdgApiConnectionError: If there's a connection issue (e.g., timeout, network error).
            HdgApiResponseError: If the API response is malformed, has an unexpected
                                 status code, or an unexpected content type.
            HdgApiError: For other unexpected API-related errors.
        """
        _LOGGER.debug(
            f"Requesting data refresh. URL: {self._url_data_refresh}, Payload: {node_payload_str}"
        )

        headers = {"Content-Type": "application/x-www-form-urlencoded; charset=UTF-8"}
        try:
            async with async_timeout.timeout(DEFAULT_TIMEOUT):
                response = await self._session.post(
                    self._url_data_refresh, data=node_payload_str, headers=headers
                )
                # Raise an exception for HTTP error codes (4xx or 5xx),
                # indicating an issue with the request or server-side processing.
                response.raise_for_status()

                # The HDG API can return various content types, even for successful JSON responses.
                # It might also return HTML for error pages (e.g., if the boiler's web server
                # itself encounters an issue not related to the API endpoint logic).
                content_type = response.headers.get("Content-Type", "")
                if (
                    "application/json" in content_type
                    or "text/json" in content_type
                    or "text/plain" in content_type  # Sometimes used for JSON by HDG
                    or "text/html" in content_type  # Check HTML as it can indicate an error page
                ):
                    try:
                        # Attempt to parse the response as JSON.
                        json_response = await response.json()
                    except aiohttp.ContentTypeError:
                        # This handles cases where the Content-Type header suggests JSON (or is HTML),
                        # but the body is not actually valid JSON. This can happen if the boiler
                        # returns an HTML error page instead of a JSON response.
                        text_response = await response.text()
                        _LOGGER.warning(
                            f"Received non-JSON response for dataRefresh (payload: {node_payload_str}) "
                            f"despite Content-Type '{content_type}'. Response: {text_response[:200]}..."
                        )
                        raise HdgApiResponseError(
                            f"Non-JSON response for dataRefresh (Content-Type: {content_type}): {text_response[:100]}"
                        )

                    if isinstance(json_response, list):
                        # Validate that the list contains the expected dictionary structure for nodes.
                        # An empty list is a valid response (e.g., no data for requested nodes or an empty payload).
                        if all(
                            isinstance(item, dict) and "id" in item and "text" in item
                            for item in json_response
                        ):
                            _LOGGER.debug(
                                f"Successfully fetched and parsed {len(json_response)} nodes."
                            )
                            return json_response
                        else:
                            # This case is hit if json_response is a non-empty list but items are malformed.
                            _LOGGER.warning(
                                f"Unexpected structure in JSON list items for dataRefresh: {str(json_response)[:200]}"
                            )
                            raise HdgApiResponseError(
                                "Unexpected item structure in dataRefresh response."
                            )
                    else:
                        # The API is expected to return a list for dataRefresh.
                        # If it's not a list, it's an unexpected response format.
                        _LOGGER.warning(
                            f"API response for dataRefresh was not a list: {str(json_response)[:200]}"
                        )
                        raise HdgApiResponseError(
                            f"Unexpected API response type for dataRefresh (not a list): {type(json_response)}"
                        )
                else:
                    # Handle unexpected content types not covered above.
                    text_response = await response.text()
                    _LOGGER.warning(
                        f"Unexpected Content-Type '{content_type}' for dataRefresh. Response text: {text_response[:200]}..."
                    )
                    raise HdgApiResponseError(
                        f"Unexpected Content-Type for dataRefresh: {content_type}"
                    )

        except asyncio.TimeoutError as err:
            _LOGGER.error(
                f"Timeout connecting to HDG API at {self._url_data_refresh} for dataRefresh: {err}"
            )
            raise HdgApiConnectionError(f"Timeout during dataRefresh: {err}") from err
        except aiohttp.ClientError as err:
            # Covers various client-side connection errors (e.g., DNS resolution, connection refused).
            _LOGGER.error(f"Client error during dataRefresh to {self._url_data_refresh}: {err}")
            raise HdgApiConnectionError(f"Client error during dataRefresh: {err}") from err
        except HdgApiResponseError:  # Re-raise our custom error if already caught and processed.
            raise
        except Exception as err:
            # Catch-all for any other unexpected errors during the process.
            _LOGGER.exception(
                f"Unexpected error during dataRefresh to {self._url_data_refresh}: {err}"
            )
            raise HdgApiError(f"Unexpected error during dataRefresh: {err}") from err
        # This line should ideally not be reached if error handling is comprehensive and exceptions are raised.
        # However, to satisfy type hinting for `-> List`, we return an empty list as a fallback
        # for truly unhandled paths, though the expectation is an exception would be raised prior.
        return []  # pragma: no cover

    async def async_set_node_value(self, node_id: str, value: str) -> bool:
        """
        Set a specific node value on the HDG boiler.

        The HDG API for setting values uses a GET request with parameters in the URL
        (e.g., /ActionManager.php?action=set_value_changed&i=NODE_ID&v=VALUE).
        A successful operation is typically indicated by an HTTP 200 status.

        Args:
            node_id: The node ID to set (e.g., "6024"). This should be the base ID without suffixes.
            value: The value to set for the node, as a string.

        Returns:
            True if the value was successfully set (HTTP 200), False otherwise.

        Raises:
            HdgApiConnectionError: If there's a connection issue (timeout, network error).
            HdgApiError: For other unexpected API-related errors.
        """
        # Ensure node_id and value are string representations for URL construction.
        node_id_str = str(node_id)
        value_str = str(value)

        url_with_params = f"{self._url_set_value_base}&i={node_id_str}&v={value_str}"
        _LOGGER.debug(f"Setting node value via GET: {url_with_params}")

        try:
            async with async_timeout.timeout(DEFAULT_TIMEOUT):
                response = await self._session.get(url_with_params)
                # Fetch response text for logging, regardless of status, as it might contain useful info.
                response_text = await response.text()

                if response.status == 200:
                    # The HDG API usually returns a simple text response (e.g., "OK") or an empty body on success.
                    # An HTTP 200 status is the primary indicator of success for set operations.
                    _LOGGER.info(
                        f"Successfully set node '{node_id_str}' to '{value_str}'. Response status: {response.status}, Text: {response_text[:100]}"
                    )
                    return True
                else:
                    # Log an error if the status code is not 200, as this indicates a failure.
                    _LOGGER.error(
                        f"Failed to set HDG node '{node_id_str}'. Status: {response.status}. Response: {response_text[:200]}"
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
        Performs a basic connectivity test by attempting to fetch a known,
        small set of nodes. This helps verify that the API is reachable and
        responding as expected without fetching all data.
        """
        # Use a minimal, predefined payload for the connectivity test.
        # This requests a few basic, static configuration nodes to verify API responsiveness.
        # Nodes 1 (Sprache/Language), 2 (Bauart/Type), 3 (Kesseltyp Kennung/Boiler Model ID)
        # are good candidates as they are fundamental and static.
        # The payload format is "nodes=ID1-ID2-ID3T".
        connectivity_test_payload_str = "nodes=1-2-3T"

        _LOGGER.debug(
            f"Performing connectivity test to {self._base_url} with payload: {connectivity_test_payload_str}"
        )
        try:
            # Attempt to get data using the minimal payload.
            data = await self.async_get_nodes_data(connectivity_test_payload_str)
            # Connectivity is considered successful if `async_get_nodes_data` returns a list
            # (even an empty one), as this means the API responded without raising a connection
            # or critical response error.
            return isinstance(data, list)
        except HdgApiError:
            # Any HdgApiError (ConnectionError, ResponseError, or base ApiError)
            # during this minimal fetch indicates a connectivity problem.
            return False
