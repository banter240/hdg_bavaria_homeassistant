"""
Network and URL related utility functions for the HDG Bavaria Boiler integration.

This module provides helpers for normalizing IPv4 host addresses and for preparing
a full base URL from user-provided host input, ensuring correct
scheme and formatting. IPv6 is not actively supported as the target device
does not use it.
"""

from __future__ import annotations

__version__ = "0.1.2"

import asyncio
import logging
import platform
from urllib.parse import urlparse, urlunparse

import async_timeout

from ..const import DOMAIN

_LOGGER = logging.getLogger(DOMAIN)


def normalize_host_for_scheme(host_address: str) -> str:
    """
    Normalize an IPv4 host address string. Uses `urllib.parse.urlparse` to handle
    IPv4 addresses and optional port numbers.

    The input 'host_address' is assumed to be already stripped of leading/trailing
    whitespace and to not include an explicit scheme (e.g., "http://").

    Args:
        host_address: The host address string to normalize.
        Expected format: "ipv4host", "ipv4host:port", "hostname", "hostname:port".

    Returns:
        The normalized host string (e.g., "192.168.1.100", "example.com:8080").
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
    if not (host := parsed.hostname):
        raise ValueError(
            f"Invalid host address format: '{host_address}'. Could not extract hostname."
        )
    port = parsed.port

    # For IPv4 and hostnames, urlparse handles them correctly.
    return f"{host}:{port}" if port else host


def prepare_base_url(host_input_original_raw: str) -> str | None:
    """
    Prepare and validate the base URL from the host input.
    Handles scheme prepending (defaults to "http" if none provided).
    Relies on `normalize_host_for_scheme` for host part processing.
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
        # Normalize the host part.
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
        # For Windows: ping -n 1 (1 packet) -w timeout_in_ms
        command_args = [
            "ping",
            "-n",
            "1",
            "-w",
            str(ping_internal_timeout_sec * 1000),
            host_to_ping,
        ]
    else:  # Linux, macOS, etc.
        # For Linux/macOS: ping -c 1 (1 packet) -W timeout_in_seconds
        command_args = [
            "ping",
            "-c",
            "1",
            "-W",
            str(ping_internal_timeout_sec),
            host_to_ping,
        ]

    try:
        async with async_timeout.timeout(timeout_seconds):
            process = await asyncio.create_subprocess_exec(
                *command_args,
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
