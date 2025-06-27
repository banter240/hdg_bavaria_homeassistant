"""Network and URL related utility functions for the HDG Bavaria Boiler integration.

This module provides helpers for preparing a full base URL from a user-provided
IPv4 address. It is designed to validate that the input is an IPv4 address,
as the target HDG boiler device does not support hostnames, ports, or IPv6.
"""

from __future__ import annotations

__version__ = "0.1.4"

import contextlib
import asyncio
import logging
import platform
import re
from urllib.parse import urlparse, urlunparse
import ipaddress

import async_timeout

from ..const import DOMAIN

_LOGGER = logging.getLogger(DOMAIN)


def normalize_host_for_scheme(host_address: str) -> str:
    """Validate that the host address is a valid IPv4 address.

    This function validates that the provided host address is a valid IPv4
    address, as this is the only format supported by the target boiler device.
    Hostnames, ports, and IPv6 addresses are not supported.

    Args:
        host_address: The host address string to validate.
                      Expected format: "192.168.1.100".

    Returns:
        The validated IPv4 address string if it passes validation.

    Raises:
        ValueError: If the host address is not a valid IPv4 address.

    """
    if not host_address:
        raise ValueError("Host address cannot be empty.")

    with contextlib.suppress(ipaddress.AddressValueError):
        ipaddress.IPv4Address(host_address)
        return host_address  # Return as is if valid IPv4

    # If not an IPv4, assume it's a hostname
    # Basic regex for hostname validation (more permissive than strict RFC)
    # Allows alphanumeric, hyphens, and dots. No leading/trailing hyphens/dots.
    hostname_pattern = re.compile(
        r"^([a-zA-Z0-9]|[a-zA-Z0-9][a-zA-Z0-9\-]*[a-zA-Z0-9])(\.([a-zA-Z0-9]|[a-zA-Z0-9][a-zA-Z0-9\-]*[a-zA-Z0-9]))*$"
    )

    if not hostname_pattern.match(host_address):
        raise ValueError(f"Invalid hostname format: '{host_address}'")

    return host_address


def prepare_base_url(host_input_original_raw: str) -> str | None:
    """Prepare and validate the base URL from a user-provided IPv4 address.

    Handles scheme prepending (defaults to "http" if none provided).
    Relies on `normalize_host_for_scheme` for host part processing to ensure
    the host is a valid IPv4 address as required by the boiler.
    Args:
        host_input_original_raw: The raw host input string from configuration,
                                 which must be a valid IPv4 address.

    Returns: The prepared base URL string (e.g., "http://192.168.1.100"), or None if the input is not a valid IPv4 address.

    """
    host_input_original = host_input_original_raw.strip()
    host_to_process = host_input_original
    scheme_provided = host_to_process.lower().startswith(("http://", "https://"))
    current_scheme = ""

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
        normalized_host = normalize_host_for_scheme(host_to_process)
    except ValueError as e:
        _LOGGER.error(
            f"Invalid host/IP format '{host_input_original_raw}' for HDG Boiler. "
            f"Normalization of host part '{host_to_process}' failed: {e}. Please check configuration."
        )
        return None
    schemed_host_input = f"{current_scheme or 'http'}://{normalized_host}"

    parsed_url = urlparse(schemed_host_input)
    if not parsed_url.netloc:
        _LOGGER.error(
            f"Invalid host/IP '{host_input_original}'. Empty netloc after processing to '{schemed_host_input}'."
        )
        return None

    return urlunparse((parsed_url.scheme, parsed_url.netloc, "", "", "", ""))


async def async_execute_icmp_ping(host_to_ping: str, timeout_seconds: int = 2) -> bool:
    """Perform an ICMP ping to check host reachability using the OS 'ping' command.

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

    ping_internal_timeout_sec = max(1, timeout_seconds - 1)

    if platform.system().lower() == "windows":
        command_args = [
            "ping",
            "-n",
            "1",
            "-w",
            str(ping_internal_timeout_sec * 1000),
            host_to_ping,
        ]
    else:
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
