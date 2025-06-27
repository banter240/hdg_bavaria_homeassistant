"""Logging utility functions for the HDG Bavaria Boiler integration."""

from __future__ import annotations

__version__ = "0.4.0"

import logging
from typing import Any

from homeassistant.config_entries import ConfigEntry

from ..const import (
    API_LOGGER_NAME,
    CONF_ADVANCED_LOGGING,
    CONF_LOG_LEVEL,
    DEFAULT_ADVANCED_LOGGING,
    DEFAULT_LOG_LEVEL,
    DOMAIN,
    ENTITY_DETAIL_LOGGER_NAME,
    HEURISTICS_LOGGER_NAME,
    LIFECYCLE_LOGGER_NAME,
    PROCESSOR_LOGGER_NAME,
    USER_ACTION_LOGGER_NAME,
)

SPAMMY_LOGGERS = [
    ENTITY_DETAIL_LOGGER_NAME,
    API_LOGGER_NAME,
    LIFECYCLE_LOGGER_NAME,
    HEURISTICS_LOGGER_NAME,
    PROCESSOR_LOGGER_NAME,
    USER_ACTION_LOGGER_NAME,
]


class AdvancedLoggingFilter(logging.Filter):
    """A logging filter that suppresses messages from specific 'spammy' loggers.

    This filter checks if the 'advanced_logging' option is enabled in the ConfigEntry.
    If it's disabled, any log record from a logger listed in SPAMMY_LOGGERS
    will be suppressed. This allows for fine-grained control over verbose logging.
    """

    def __init__(self, entry: ConfigEntry, name: str = "") -> None:
        """Initialize the filter with the config entry."""
        super().__init__(name)
        self.entry = entry

    def filter(self, record: logging.LogRecord) -> bool:
        """Filter log records based on the advanced logging setting."""
        # This filter only acts on records from the spammy loggers list.
        # All other records are allowed to pass through.
        if record.name not in SPAMMY_LOGGERS:
            return True

        # For a spammy logger, the record is only passed if advanced logging is on.
        return bool(
            self.entry.options.get(CONF_ADVANCED_LOGGING, DEFAULT_ADVANCED_LOGGING)
        )


def format_for_log(obj: Any, max_len: int = 150) -> str:
    """Format an object for logging, truncating it if it is too long."""
    try:
        s = str(obj)
    except Exception:
        return f"(un-string-able object of type {type(obj).__name__})"

    return f"{s[: max_len - 3]}..." if len(s) > max_len else s


def make_log_prefix(node_id: str | None, entity_name: str | None) -> str:
    """Create a consistent log prefix for a given node ID and entity name."""
    parts = []
    if entity_name:
        parts.append(f"[{entity_name}]")
    if node_id:
        parts.append(f"[{node_id}]")

    return "".join(parts) + " " if parts else ""


def configure_loggers(entry: ConfigEntry) -> None:
    """Set up the integration's loggers based on user configuration."""
    log_level_str = entry.options.get(CONF_LOG_LEVEL, DEFAULT_LOG_LEVEL).upper()
    log_level = getattr(logging, log_level_str, logging.INFO)
    is_advanced = entry.options.get(CONF_ADVANCED_LOGGING, DEFAULT_ADVANCED_LOGGING)

    # This filter is attached to spammy loggers to suppress their output
    # unless advanced logging is explicitly enabled by the user.
    advanced_filter = AdvancedLoggingFilter(entry)

    # The main logger is configured directly and does not need the advanced filter.
    domain_logger = logging.getLogger(DOMAIN)
    domain_logger.setLevel(log_level)
    domain_logger.filters = []

    # Configure spammy loggers to be filtered at the source.
    for logger_name in SPAMMY_LOGGERS:
        logger = logging.getLogger(logger_name)
        logger.setLevel(log_level)
        logger.filters = [advanced_filter]
        logger.propagate = True

    domain_logger.info(
        "HDG Bavaria Boiler integration log level set to '%s'. Advanced logging is %s.",
        log_level_str,
        "ON" if is_advanced else "OFF",
    )
