"""HDG Boiler API."""

from ..exceptions import HdgApiConnectionError, HdgApiError, HdgApiResponseError
from .client import HdgApiClient
from .protocols import HdgApiProtocol, ProtocolV1, ProtocolV2

__all__ = [
    "HdgApiClient",
    "HdgApiProtocol",
    "ProtocolV1",
    "ProtocolV2",
    "HdgApiConnectionError",
    "HdgApiError",
    "HdgApiResponseError",
]
