"""API client for interacting with the HDG Bavaria Boiler web interface.

This module provides the `HdgApiClient` class, which facilitates HTTP
communication with the HDG Bavaria boiler's web API. It is responsible for
formatting requests, parsing responses, managing errors, and providing
methods to fetch data and set values on the boiler.
"""

import functools
import logging
import time
from typing import Any, Concatenate
from collections.abc import Awaitable, Callable

import aiohttp

from .const import (
    API_ENDPOINT_DATA_REFRESH,
    API_ENDPOINT_SET_VALUE,
    DOMAIN,
    LIFECYCLE_LOGGER_NAME,
    API_LOGGER_NAME,
)
from .exceptions import (
    HdgApiConnectionError,
    HdgApiError,
    HdgApiResponseError,
)
from .helpers.network_utils import prepare_base_url
from .helpers.logging_utils import format_for_log

_LOGGER = logging.getLogger(DOMAIN)
_LIFECYCLE_LOGGER = logging.getLogger(LIFECYCLE_LOGGER_NAME)
_API_LOGGER = logging.getLogger(API_LOGGER_NAME)


def handle_api_errors[T, **P](
    func: Callable[Concatenate["HdgApiClient", P], Awaitable[T]],
) -> Callable[Concatenate["HdgApiClient", P], Awaitable[T]]:
    """Decorate API methods to handle common exceptions and re-raise as HdgApiErrors."""

    @functools.wraps(func)
    async def wrapper(self: "HdgApiClient", *args: P.args, **kwargs: P.kwargs) -> T:
        """Wrap the API call with error handling."""
        start_time = time.monotonic()
        try:
            return await func(self, *args, **kwargs)
        except TimeoutError as err:
            duration = time.monotonic() - start_time
            _LOGGER.warning(
                "API Client: Total request timed out after %.2fs for %s. Check network or increase 'api_timeout' in options (currently %ss).",
                duration,
                func.__name__,
                self._api_timeout,
            )
            raise HdgApiConnectionError(
                f"Total request timeout after {duration:.2f}s"
            ) from err
        except aiohttp.ClientConnectorError as err:
            duration = time.monotonic() - start_time
            _LOGGER.warning(
                "API Client: Connection error for %s to %s after %.2fs. Check network and host IP. Error: %s",
                func.__name__,
                self._base_url,
                duration,
                err,
            )
            raise HdgApiConnectionError(
                f"Connection error for {func.__name__}: {err}"
            ) from err
        except aiohttp.ClientError as err:
            duration = time.monotonic() - start_time
            _LOGGER.warning(
                "API Client: Client error during %s to %s after %.2fs: %s",
                func.__name__,
                self._base_url,
                duration,
                err,
            )
            raise HdgApiConnectionError(
                f"Client error during {func.__name__}: {err}"
            ) from err
        except HdgApiError:
            raise  # Re-raise HdgApiError subtypes without modification
        except Exception as err:
            duration = time.monotonic() - start_time
            _LOGGER.exception(
                "API Client: Unexpected error during %s to %s after %.2fs: %s",
                func.__name__,
                self._base_url,
                duration,
                err,
            )
            raise HdgApiError(
                f"Unexpected error during {func.__name__}: {err}"
            ) from err

    return wrapper


class HdgApiClient:
    """Client to interact with the HDG Boiler API.

    Handles HTTP communication, request formatting, response parsing, and error
    management for fetching data from and setting values on the HDG boiler. It
    ensures that host addresses are correctly formatted and manages API endpoints.
    """

    def __init__(
        self,
        session: aiohttp.ClientSession,
        host_address: str,
        api_timeout: float,
        connect_timeout: float,
    ) -> None:
        """Initialize the API client.

        Args:
            session: An `aiohttp.ClientSession` instance for making HTTP requests.
            host_address: The host address (IP or hostname) of the HDG boiler.
                          The client will ensure this address is prefixed with 'http://'
                          if no scheme is provided.
            api_timeout: The total timeout for API requests in seconds.
            connect_timeout: The timeout for establishing a connection in seconds.

        Raises:
            HdgApiError: If the `host_address` is invalid (e.g., results in an empty netloc).

        """
        self._session = session
        self._api_timeout = api_timeout
        self._connect_timeout = connect_timeout
        _LIFECYCLE_LOGGER.debug(
            "HdgApiClient initialized with api_timeout: %ss, connect_timeout: %ss",
            self._api_timeout,
            self._connect_timeout,
        )
        self._aiohttp_timeout_obj = aiohttp.ClientTimeout(
            total=self._api_timeout, connect=self._connect_timeout
        )

        prepared_base_url = prepare_base_url(host_address)
        if not prepared_base_url:
            _LOGGER.error(
                "Failed to prepare base URL from host_address '%s'.", host_address
            )
            raise HdgApiError(f"Invalid host_address provided: '{host_address}'.")

        self._base_url = prepared_base_url
        self._url_data_refresh = f"{self._base_url}{API_ENDPOINT_DATA_REFRESH}"
        self._url_set_value_base = f"{self._base_url}{API_ENDPOINT_SET_VALUE}"

    @property
    def base_url(self) -> str:
        """Return the base URL of the HDG boiler API."""
        return self._base_url

    async def _async_parse_json_response(
        self, response: aiohttp.ClientResponse, context_info: str
    ) -> Any:
        """Parse JSON response, handling content type and parsing errors.

        Args:
            response: The aiohttp.ClientResponse object.
            context_info: Additional context for logging (e.g., payload string).

        Returns:
            The parsed JSON response.

        Raises:
            HdgApiResponseError: If content type is unexpected or JSON parsing fails.

        """
        content_type_header = response.headers.get("Content-Type", "").lower()

        if all(
            accepted_type not in content_type_header
            for accepted_type in ("application/json", "text/json", "text/plain")
        ):
            text_response = await response.text()
            if "text/html" in content_type_header:
                _LOGGER.warning(
                    "Received HTML response (context: %s). Content-Type: %s, Content: %s",
                    context_info,
                    content_type_header,
                    format_for_log(text_response),
                )
                raise HdgApiResponseError(
                    f"Received HTML error page. Content: {format_for_log(text_response)}"
                )
            else:
                _LOGGER.error(
                    "Unexpected Content-Type '%s' (context: %s). Response text: %s",
                    content_type_header,
                    context_info,
                    format_for_log(text_response),
                )
                raise HdgApiResponseError(
                    f"Unexpected Content-Type: {content_type_header}"
                )

        try:
            json_response = await response.json()
        except (aiohttp.ContentTypeError, ValueError) as err:
            text_response_for_error = await response.text()
            formatted_error_text = format_for_log(text_response_for_error)
            _LOGGER.warning(
                "Failed to parse JSON response (context: %s) despite Content-Type '%s'. Error: %s. Response: %s",
                context_info,
                content_type_header,
                err,
                formatted_error_text,
            )
            raise HdgApiResponseError(
                f"Failed to parse JSON response (Content-Type: {content_type_header}, Error: {err}): {formatted_error_text}"
            ) from err
        return json_response

    @handle_api_errors
    async def async_get_nodes_data(self, node_payload_str: str) -> list[dict[str, Any]]:
        """Fetch data for a specified set of nodes from the HDG boiler."""
        _API_LOGGER.debug(
            "Requesting data refresh. URL: %s, Payload: %s",
            self._url_data_refresh,
            node_payload_str,
        )
        headers = {"Content-Type": "application/x-www-form-urlencoded; charset=UTF-8"}
        context = f"dataRefresh (payload: {node_payload_str})"

        async with self._session.post(
            self._url_data_refresh,
            data=node_payload_str,
            headers=headers,
            timeout=self._aiohttp_timeout_obj,
        ) as response:
            json_response = await self._async_parse_json_response(response, context)
            if not isinstance(json_response, list):
                _LOGGER.error(
                    "API response for dataRefresh (payload: %s) was not a list: %s",
                    node_payload_str,
                    format_for_log(json_response),
                )
                raise HdgApiResponseError(
                    f"Unexpected API response type for dataRefresh (not a list): {type(json_response)}"
                )
            return [
                item
                for item in json_response
                if isinstance(item, dict) and "id" in item and "text" in item
            ]

    @handle_api_errors
    async def async_set_node_value(self, node_id: str, value: str) -> bool:
        """Set a specific node value on the HDG boiler."""
        _API_LOGGER.debug("Setting node '%s' to '%s' via GET.", node_id, value)

        params = {"i": node_id, "v": value}
        async with self._session.get(
            self._url_set_value_base, params=params, timeout=self._aiohttp_timeout_obj
        ) as response:
            response_text = await response.text()
            if response.status == 200:
                _API_LOGGER.debug(
                    "Successfully set node '%s' to '%s'. Response status: %s, Text: %s",
                    node_id,
                    value,
                    response.status,
                    format_for_log(response_text),
                )
                return True
            else:
                _LOGGER.error(
                    "Failed to set HDG node '%s'. Status: %s. Response: %s",
                    node_id,
                    response.status,
                    format_for_log(response_text),
                )
                raise HdgApiResponseError(
                    f"Failed to set node {node_id}. Status: {response.status}, Response: {format_for_log(response_text)}"
                )
