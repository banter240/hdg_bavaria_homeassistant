"""API client for interacting with the HDG Bavaria Boiler web interface.

This module provides the `HdgApiClient` class, which facilitates HTTP
communication with the HDG Bavaria boiler's web API. It is responsible for
formatting requests, parsing responses, managing errors, and providing
methods to fetch data and set values on the boiler.
"""

__version__ = "0.8.30"

import asyncio
import logging
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

import aiohttp
import async_timeout

from .const import (
    API_ENDPOINT_DATA_REFRESH,
    API_ENDPOINT_SET_VALUE,
    API_TIMEOUT,
    DOMAIN,
)
from .exceptions import (
    HdgApiConnectionError,
    HdgApiError,
    HdgApiResponseError,
)
from .helpers.network_utils import async_execute_icmp_ping, normalize_host_for_scheme

_LOGGER = logging.getLogger(DOMAIN)


class HdgApiClient:
    """Client to interact with the HDG Boiler API.

    Handles HTTP communication, request formatting, response parsing, and error
    management for fetching data from and setting values on the HDG boiler. It
    ensures that host addresses are correctly formatted and manages API endpoints.
    """

    def __init__(self, session: aiohttp.ClientSession, host_address: str) -> None:
        """Initialize the API client.

        Args:
            session: An `aiohttp.ClientSession` instance for making HTTP requests.
            host_address: The host address (IP or hostname) of the HDG boiler.
                          The client will ensure this address is prefixed with 'http://'
                          if no scheme is provided.

        Raises:
            HdgApiError: If the `host_address` is invalid (e.g., results in an empty netloc).

        """
        self._session = session
        # Ensure host_address is not empty or just whitespace.
        host_address_stripped = host_address.strip()
        if not host_address_stripped:
            _LOGGER.error("Provided host_address is empty after stripping whitespace.")
            raise HdgApiError("host_address must not be empty or whitespace only.")

        if not host_address_stripped.lower().startswith(("http://", "https://")):
            temp_host_for_scheme = host_address_stripped
            try:
                normalized_host_part = normalize_host_for_scheme(temp_host_for_scheme)
                schemed_host_input = f"http://{normalized_host_part}"
            # Handle errors during host normalization.
            except ValueError as e:
                _LOGGER.warning(
                    f"Invalid host_address format '{host_address_stripped}' for API client. "
                    f"Normalization failed: {e}. Please check your configuration."
                )
                # Re-raise as HdgApiError to be consistent with other init failures.
                raise HdgApiError(f"Invalid host_address format: {e}") from e
        else:
            schemed_host_input = host_address_stripped
        # Parse the schemed host input and validate the network location.
        parsed_url = urlparse(schemed_host_input)
        if not parsed_url.netloc:
            _LOGGER.error(
                f"Invalid host_address '{host_address_stripped}' for API client. "
                f"Expected a valid hostname or IPv4 address, optionally with a port (e.g., '192.168.1.100', 'example.com:8080'). "
                f"Input after scheme normalization: '{schemed_host_input}', Parsed URL: {parsed_url}. "
                "Please check your configuration and ensure the host_address is in the correct format."
            )
            raise HdgApiError(
                f"Invalid host_address for API client: '{host_address}'. "
                f"Expected a valid hostname or IPv4 address, optionally with a port (e.g., '192.168.1.100', 'example.com:8080'). "
                "Please check your configuration."
            )

        # Construct base URLs for API endpoints.
        self._base_url = urlunparse(
            (parsed_url.scheme, parsed_url.netloc, "", "", "", "")
        )
        self._url_data_refresh = f"{self._base_url}{API_ENDPOINT_DATA_REFRESH}"
        self._url_set_value_base = f"{self._base_url}{API_ENDPOINT_SET_VALUE}"

    @property
    def base_url(self) -> str:
        """Return the base URL of the HDG boiler API."""
        return self._base_url

    async def async_pre_check_host_reachability(self) -> bool:
        """Perform a pre-check to see if the host is reachable via ICMP ping.

        Returns:
            True if the host is reachable, False otherwise.

        """
        parsed_url = urlparse(self._base_url)
        host_to_ping = parsed_url.hostname
        if not host_to_ping:
            _LOGGER.error(
                f"Could not extract hostname from base_url '{self._base_url}' for pre-check."
            )
            return False
        # Using a short timeout for the pre-check ping.
        return await async_execute_icmp_ping(host_to_ping, timeout_seconds=3)

    async def _async_handle_data_refresh_response(
        self, response: aiohttp.ClientResponse, node_payload_str: str
    ) -> list[dict[str, Any]]:
        """Handle and parse the response from the dataRefresh API endpoint.

        Args:
            response: The aiohttp.ClientResponse object.
            node_payload_str: The original payload string, for logging context.

        Returns:
            A list of node data dictionaries.

        Raises:
            HdgApiResponseError: If the response is malformed, has an unexpected
                                 status code, or an unexpected content type.
            aiohttp.ClientResponseError: If response.raise_for_status() detects an HTTP error.

        """  # noqa: D402
        # Ensure the response status indicates success.
        response.raise_for_status()

        content_type_header = response.headers.get("Content-Type", "").lower()
        # Extract the main content type, ignoring charset or other parameters.
        content_type_main = content_type_header.split(";")[0].strip()

        if content_type_main == "text/plain":
            _LOGGER.warning(
                f"Accepting 'text/plain' as JSON response for dataRefresh (payload: {node_payload_str}). "
                "This may mask unexpected server responses or misconfigurations."
            )
        # Check if the content type is one of the accepted JSON-like types.
        if all(
            accepted_type not in content_type_header
            for accepted_type in ("application/json", "text/json", "text/plain")
        ):
            text_response = await response.text()
            if "text/html" in content_type_header:
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

        # Attempt to parse the response as JSON.
        try:
            json_response = await response.json()
        except (
            aiohttp.ContentTypeError,
            ValueError,
        ) as err:
            text_response_for_error = await response.text()
            _LOGGER.warning(
                f"Failed to parse JSON response for dataRefresh (payload: {node_payload_str}) "
                f"despite Content-Type '{content_type_header}'. Error: {err}. Response: {text_response_for_error[:200]}..."
            )
            raise HdgApiResponseError(
                f"Failed to parse JSON response (Content-Type: {content_type_header}, Error: {err}): {text_response_for_error[:100]}"
            ) from err

        # Validate that the JSON response is a list, as expected.
        if not isinstance(json_response, list):
            _LOGGER.error(
                f"API response for dataRefresh (payload: {node_payload_str}) was not a list: {str(json_response)[:200]}"
            )
            raise HdgApiResponseError(
                f"Unexpected API response type for dataRefresh (not a list): {type(json_response)}"
            )

        valid_items: list[dict[str, Any]] = []
        malformed_item_indices: list[int] = []

        # Iterate through items in the JSON list, validating each one.
        for idx, item in enumerate(json_response):
            if not isinstance(item, dict):
                _LOGGER.warning(
                    f"Item at index {idx} in dataRefresh response (payload: {node_payload_str}) is not a dict: {item!r}. Skipping."
                )
                malformed_item_indices.append(idx)
                continue

            # Check for required fields 'id' and 'text'.
            if missing_fields := [
                field for field in ("id", "text") if field not in item
            ]:
                _LOGGER.warning(
                    f"Item at index {idx} in dataRefresh response (payload: {node_payload_str}) is missing required fields {missing_fields}: {item!r}. Skipping."
                )
                malformed_item_indices.append(idx)
                continue

            # Log if unexpected fields are present, but still process the item.
            if unexpected_fields := set(item.keys()) - {"id", "text"}:
                _LOGGER.info(
                    f"Item at index {idx} in dataRefresh response (payload: {node_payload_str}) "
                    f"has unexpected fields {unexpected_fields}: {item!r}"
                )
            valid_items.append(item)

        _LOGGER.debug(
            f"Successfully parsed {len(valid_items)} valid nodes from dataRefresh response (payload: {node_payload_str}). "
            f"{len(malformed_item_indices)} items were skipped due to malformation or missing required fields."
        )
        return valid_items

    async def async_get_nodes_data(self, node_payload_str: str) -> list[dict[str, Any]]:
        """Fetch data for a specified set of nodes from the HDG boiler.

        Includes a pre-check using ICMP ping.

        Args:
            node_payload_str: The payload string specifying which nodes to fetch.

        Returns:
            A list of dictionaries, where each dictionary represents a node's data.

        Raises:
            HdgApiConnectionError: If the ICMP pre-check fails or a connection error occurs.
            HdgApiError: For other API-related errors.

        """
        if not await self.async_pre_check_host_reachability():
            _LOGGER.warning(
                f"ICMP pre-check to host for {self._base_url} failed. Skipping data refresh for payload: {node_payload_str}"
            )
            raise HdgApiConnectionError(
                f"ICMP pre-check failed for host of {self._base_url}"
            )

        _LOGGER.debug(
            f"Requesting data refresh. URL: {self._url_data_refresh}, Payload: {node_payload_str}"
        )
        headers = {"Content-Type": "application/x-www-form-urlencoded; charset=UTF-8"}
        try:
            async with (
                async_timeout.timeout(API_TIMEOUT),
                self._session.post(
                    self._url_data_refresh, data=node_payload_str, headers=headers
                ) as response,
            ):
                return await self._async_handle_data_refresh_response(
                    response, node_payload_str
                )
        except asyncio.TimeoutError as err:  # noqa: UP041
            _LOGGER.error(
                f"Timeout connecting to HDG API at {self._url_data_refresh} for dataRefresh (payload: {node_payload_str}): {err}"
            )
            raise HdgApiConnectionError(f"Timeout during dataRefresh: {err}") from err
        except aiohttp.ClientError as err:
            _LOGGER.error(
                f"Client error during dataRefresh to {self._url_data_refresh} (payload: {node_payload_str}): {err}"
            )
            raise HdgApiConnectionError(
                f"Client error during dataRefresh: {err}"
            ) from err
        except HdgApiError:
            raise
        except Exception as err:
            if isinstance(err, KeyboardInterrupt | SystemExit):
                raise
            _LOGGER.exception(
                f"Unexpected error during dataRefresh to {self._url_data_refresh} (payload: {node_payload_str}): {err}",
            )
            raise HdgApiError(
                f"Unexpected error during dataRefresh: {err}"
            ) from err  # Ensure HdgApiError is raised

    async def async_set_node_value(self, node_id: str, value: str) -> bool:
        """Set a specific node value on the HDG boiler.

        Includes a pre-check using HTTP HEAD.

        Args:
            node_id: The ID of the node to set.
            value: The string value to set for the node.

        Returns:
            True if the value was set successfully, False otherwise.

        Raises:
            HdgApiConnectionError: If the HTTP pre-check fails or a connection error occurs.
            HdgApiResponseError: If the API returns an error status for the set operation.
            HdgApiError: For other API-related errors.

        """
        if not await self.async_pre_check_host_reachability():
            _LOGGER.warning(
                f"ICMP pre-check to host for {self._base_url} failed. Skipping set_node_value for node {node_id}"
            )
            raise HdgApiConnectionError(
                f"ICMP pre-check failed for host of {self._base_url}"
            )

        base_url_parts = urlparse(self._url_set_value_base)
        # Combine existing query parameters with the new node_id and value.
        existing_query_list = parse_qsl(base_url_parts.query, keep_blank_values=True)
        existing_query_dict = dict(existing_query_list) | {"i": node_id, "v": value}
        new_query_string = urlencode(existing_query_dict)

        url_with_params = urlunparse(base_url_parts._replace(query=new_query_string))
        _LOGGER.debug(
            f"Setting node '{node_id}' to '{value}' via GET: {url_with_params}"
        )
        try:
            async with (
                async_timeout.timeout(API_TIMEOUT),
                self._session.get(url_with_params) as response,
            ):
                response_text = await response.text()
                if response.status == 200:
                    _LOGGER.debug(
                        f"Successfully set node '{node_id}' to '{value}'. Response status: {response.status}, Text: {response_text[:100]}"
                    )
                    return True
                else:
                    _LOGGER.error(
                        f"Failed to set HDG node '{node_id}'. Status: {response.status}. Response: {response_text[:200]}"
                    )
                    raise HdgApiResponseError(
                        f"Failed to set node {node_id}. Status: {response.status}, Response: {response_text[:100]}"
                    )
        except asyncio.TimeoutError as err:  # noqa: UP041
            _LOGGER.error(
                f"Timeout connecting to HDG API at {url_with_params} for set_node_value: {err}"
            )
            raise HdgApiConnectionError(
                f"Timeout during set_node_value: {err}"
            ) from err
        except aiohttp.ClientError as err:
            _LOGGER.error(
                f"Client error during set_node_value to {url_with_params}: {err}"
            )
            raise HdgApiConnectionError(
                f"Client error during set_node_value: {err}"
            ) from err
        except HdgApiError:  # Re-raise HdgApiErrors
            raise
        except Exception as err:
            _LOGGER.exception(
                f"Unexpected error during set_node_value to {url_with_params}: {err}"
            )
            raise HdgApiError(f"Unexpected error during set_node_value: {err}") from err

    async def async_check_connectivity(self) -> bool:
        """Perform a basic connectivity test to the HDG boiler API.

        Uses an ICMP ping to the host.

        Returns:
            True if the boiler's host is reachable via ICMP ping,
            False otherwise.

        """
        _LOGGER.debug(
            f"Performing connectivity test (ICMP ping) to host of {self._base_url}"
        )

        return await self.async_pre_check_host_reachability()
