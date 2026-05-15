"""Network and URL related utility functions for the HDG Bavaria Boiler integration.

This module provides helpers for preparing a base URL from a host address
(IPv4 or hostname) and for checking host reachability via ICMP ping.
"""

from __future__ import annotations


import asyncio
import logging
import platform
import re
from urllib.parse import urlparse, urlunparse

import async_timeout

from ..const import DOMAIN

_LOGGER = logging.getLogger(DOMAIN)

__all__ = ["prepare_base_url", "async_execute_icmp_ping"]

# Matches a valid hostname label: letters, digits, hyphens (RFC 1123)
_HOSTNAME_RE = re.compile(
    r"^(?:[a-zA-Z0-9](?:[a-zA-Z0-9\-]{0,61}[a-zA-Z0-9])?\.)*"
    r"[a-zA-Z0-9](?:[a-zA-Z0-9\-]{0,61}[a-zA-Z0-9])?$"
)


def prepare_base_url(host_input: str) -> str | None:
    """Prepare and validate the base URL from a host address or hostname.

    Accepts an IPv4 address (e.g. ``192.168.1.100``) or a DNS hostname
    (e.g. ``hdg-boiler.fritz.box``). Prepends ``http://`` when no scheme is
    given. Port numbers are not supported.

    Returns the normalised base URL or ``None`` if the input is invalid.
    """
    if not host_input:
        _LOGGER.error("Host address cannot be empty.")
        return None

    host_input = host_input.strip()
    if "://" not in host_input:
        host_input = f"http://{host_input}"

    try:
        parsed_url = urlparse(host_input)
        host = parsed_url.hostname

        if not host or not _HOSTNAME_RE.match(host):
            raise ValueError(f"'{host}' is not a valid IPv4 address or hostname.")

        if parsed_url.port:
            raise ValueError("Port specification is not supported.")

        return urlunparse((parsed_url.scheme, host, "", "", "", ""))

    except ValueError as e:
        _LOGGER.error(
            "Invalid host format for HDG Boiler: %s. Original input: '%s'",
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
