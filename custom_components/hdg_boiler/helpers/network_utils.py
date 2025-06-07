"""
Network and URL related utility functions for the HDG Bavaria Boiler integration.

This module provides helpers for normalizing host addresses, particularly for IPv6,
and for preparing a full base URL from user-provided host input, ensuring correct
scheme and formatting.
"""

from __future__ import annotations

__version__ = "0.1.2"

import asyncio
import ipaddress
import logging
import platform
from urllib.parse import urlparse, urlunparse

import async_timeout

from ..const import DOMAIN

_LOGGER = logging.getLogger(DOMAIN)


def normalize_host_for_scheme(host_address: str) -> str:
    """
    Normalize a host address string, particularly for IPv6 addresses and ports. Uses
    `urllib.parse.urlparse` and `ipaddress` to robustly handle IPv4, IPv6 addresses
    (with or without brackets), and optional port numbers.

    The input 'host_address' is assumed to be already stripped of leading/trailing
    whitespace and to not include an explicit scheme (e.g., "http://").

    Args:
        host_address: The host address string to normalize.
        Expected format: "host", "host:port", "[ipv6]", "[ipv6]:port".

    Returns:
        The normalized host string (e.g., "192.168.1.100", "[::1]", "example.com:8080"),
        with IPv6 addresses bracketed if necessary, and the port appended if present.
        The scheme (e.g., "http://") is NOT included in the return value.

    Raises:
        ValueError: If the host address is invalid or cannot be parsed into a valid
        hostname.
    """
    if not host_address:
        raise ValueError("Host address cannot be empty.")

    # Temporarily prepend a scheme to allow urlparse to correctly identify hostname and port.
    # The scheme itself is not used in the final output of this function.
    parsed = urlparse(f"scheme://{host_address}")
    host = parsed.hostname
    port = parsed.port

    if not host:
        raise ValueError(
            f"Invalid host address format: '{host_address}'. Could not extract hostname."
        )

    try:
        # Check if the host is a valid IP address to handle IPv6 bracketing.
        ip = ipaddress.ip_address(host)
        host_part_normalized = f"[{host}]" if ip.version == 6 else host
    except ValueError:
        # Not an IP address, assume it's a hostname.
        host_part_normalized = host

    return f"{host_part_normalized}:{port}" if port else host_part_normalized


def prepare_base_url(host_input_original_raw: str) -> str | None:
    """
    Prepare and validate the base URL from the host input.
    Handles scheme prepending (defaults to "http" if none provided) and
    IPv6 normalization for the host part.

    Args:
        host_input_original_raw: The raw host input string from configuration.

    Returns: The prepared base URL string (e.g., "http://192.168.1.100"),
             or None if the input is invalid or cannot be processed.
    """
    host_input_original = host_input_original_raw.strip()
    host_to_process = host_input_original
    scheme_provided = host_to_process.lower().startswith(("http://", "https://"))
    current_scheme = ""
    # If a scheme is provided, extract it and the netloc part.

    if scheme_provided:
        parsed_for_scheme = urlparse(host_to_process)
        current_scheme = parsed_for_scheme.scheme
        host_to_process = parsed_for_scheme.netloc
        if not host_to_process:
            _LOGGER.error(
                f"Invalid host/IP '{host_input_original_raw}'. Contains scheme but empty host part."
            )
            return None
    try:
        # Normalize the host part (e.g., add brackets for IPv6).
        normalized_host = normalize_host_for_scheme(host_to_process)
    except ValueError as e:
        _LOGGER.error(
            f"Invalid host/IP format '{host_input_original_raw}' for HDG Boiler. "
            f"Normalization of host part '{host_to_process}' failed: {e}. Please check configuration."
        )
        return None
    # Reconstruct the schemed host input.
    schemed_host_input = f"{current_scheme or 'http'}://{normalized_host}"

    parsed_url = urlparse(schemed_host_input)
    if not parsed_url.netloc:
        _LOGGER.error(
            f"Invalid host/IP '{host_input_original}'. Empty netloc after processing to '{schemed_host_input}'."
        )
        return None

    # Return only the scheme and netloc part for the base URL.
    return urlunparse((parsed_url.scheme, parsed_url.netloc, "", "", "", ""))


async def async_execute_icmp_ping(host_to_ping: str, timeout_seconds: int = 2) -> bool:
    """
    Perform an ICMP ping to check host reachability using the OS 'ping' command.

    Args:
        host_to_ping: The hostname or IP address to ping.
        timeout_seconds: The timeout for the ping command execution.

    Returns:
        True if the host is reachable via ICMP ping, False otherwise.
    """
    if not host_to_ping:
        _LOGGER.warning("ICMP Ping: host_to_ping was empty or None.")
        return False

    _LOGGER.debug(
        f"Performing ICMP ping to {host_to_ping} with timeout {timeout_seconds}s"
    )

    # Platform-dependent ping command
    # -c 1 (Linux/macOS) / -n 1 (Windows): send 1 packet
    # -W 1 (Linux/macOS in seconds) / -w 1000 (Windows in ms): timeout for ping response
    # We use a slightly shorter internal ping timeout than the subprocess timeout.
    ping_internal_timeout_sec = max(1, timeout_seconds - 1)

    if platform.system().lower() == "windows":
        command = f"ping -n 1 -w {ping_internal_timeout_sec * 1000} {host_to_ping}"
    else:  # Linux, macOS, etc.
        command = f"ping -c 1 -W {ping_internal_timeout_sec} {host_to_ping}"

    try:
        async with async_timeout.timeout(timeout_seconds):
            process = await asyncio.create_subprocess_shell(
                command,
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.DEVNULL,
            )
            return_code = await process.wait()
        _LOGGER.debug(
            f"ICMP ping to {host_to_ping} finished with return code: {return_code}"
        )
        return return_code == 0
    except TimeoutError:
        _LOGGER.debug(
            f"ICMP ping to {host_to_ping} timed out after {timeout_seconds}s (subprocess execution)."
        )
        return False
    except Exception as e:
        _LOGGER.error(f"Error during ICMP ping to {host_to_ping}: {e}")
        return False
