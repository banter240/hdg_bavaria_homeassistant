"""Custom exceptions for the HDG Bavaria Boiler integration.

These exceptions provide a structured way to handle errors specific to
the interaction with the HDG Bavaria boiler's API, allowing for more
granular error handling and reporting within the integration.
"""

__version__ = "0.1.2"


class HdgApiError(Exception):
    """Base exception for all errors originating from the HDG API client.

    This serves as a general catch-all for issues related to API communication
    or response processing that are not covered by more specific exceptions.
    """


class HdgApiConnectionError(HdgApiError):
    """Raised when there's an issue connecting to the HDG API.

    This typically indicates network problems, such as timeouts, DNS resolution
    failures, or the boiler being unreachable.
    """


class HdgApiResponseError(HdgApiError):
    """Raised when the HDG API returns an unexpected or error response (e.g., non-JSON, bad HTTP status code)."""


class HdgApiPreemptedError(HdgApiError):
    """Raised when a lower-priority API request is preempted by a higher-priority request."""
