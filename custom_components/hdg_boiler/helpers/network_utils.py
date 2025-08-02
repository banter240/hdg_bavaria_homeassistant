"""Network and URL related utility functions for the HDG Bavaria Boiler integration.

This module provides helpers for preparing a base URL from an IPv4 address
and for checking host reachability via ICMP ping.
"""

from __future__ import annotations

__version__ = "0.2.0"

import asyncio
import ipaddress
import logging
import platform
from urllib.parse import urlparse, urlunparse

import async_timeout

from ..const import DOMAIN

_LOGGER = logging.getLogger(DOMAIN)

__all__ = ["prepare_base_url", "async_execute_icmp_ping"]


def _is_valid_ipv4(address: str) -> bool:
    """Check if the given string is a valid IPv4 address."""
    try:
        ipaddress.IPv4Address(address)
        return True
    except ipaddress.AddressValueError:
        return False


def prepare_base_url(host_input: str) -> str | None:
    """Prepare and validate the base URL from a user-provided IPv4 address.

    Ensures the host is a valid IPv4 address and prepends 'http://' if no
    scheme is provided. The boiler device only supports IPv4.

    Args:
        host_input: The raw host input string from configuration.

    Returns:
        The prepared base URL (e.g., "http://192.168.1.100"), or None on failure.

    """
    if not host_input:
        _LOGGER.error("Host address cannot be empty.")
        return None

    host_input = host_input.strip()
    # Add a default scheme if one is missing, to allow urlparse to work correctly
    if "://" not in host_input:
        host_input = f"http://{host_input}"

    try:
        parsed_url = urlparse(host_input)
        host = parsed_url.hostname

        if not host or not _is_valid_ipv4(host):
            raise ValueError(f"Host part '{host}' is not a valid IPv4 address.")

        if parsed_url.port:
            raise ValueError("Port specification is not supported.")

        # Reconstruct the URL with only the scheme and valid hostname
        return urlunparse((parsed_url.scheme, host, "", "", "", ""))

    except ValueError as e:
        _LOGGER.error(
            "Invalid host/IP format for HDG Boiler: %s. Original input: '%s'",
            e,
            host_input,
        )
        return None


async def async_execute_icmp_ping(host: str, timeout: int = 2) -> bool:
    """Perform an ICMP ping to check host reachability.

    Args:
        host: The hostname or IP address to ping.
        timeout: The timeout for the ping command execution.

    Returns:
        True if the host is reachable, False otherwise.

    """
    if not host:
        _LOGGER.warning("ICMP Ping: host was empty or None.")
        return False

    _LOGGER.debug("Performing ICMP ping to %s with timeout %ds", host, timeout)

    ping_timeout_os = max(1, timeout - 1)
    ping_cmd = (
        ["ping", "-n", "1", "-w", str(ping_timeout_os * 1000), host]
        if platform.system().lower() == "windows"
        else ["ping", "-c", "1", "-W", str(ping_timeout_os), host]
    )

    try:
        async with async_timeout.timeout(timeout):
            process = await asyncio.create_subprocess_exec(
                *ping_cmd,
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.DEVNULL,
            )
            return_code = await process.wait()
        _LOGGER.debug(
            "ICMP ping to %s finished with return code: %d", host, return_code
        )
        return return_code == 0
    except TimeoutError:
        _LOGGER.debug("ICMP ping to %s timed out after %ds", host, timeout)
        return False
    except FileNotFoundError:
        _LOGGER.error("ICMP ping command not found. Cannot check host reachability.")
        return False
    except Exception as e:
        _LOGGER.error("Error during ICMP ping to %s: %s", host, e)
        return False
