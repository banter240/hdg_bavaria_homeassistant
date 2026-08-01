"""Logging utility functions for the HDG Bavaria Boiler integration."""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from homeassistant.config_entries import ConfigEntry

from ..const import (
    API_LOGGER_NAME,
    CONF_ADVANCED_LOGGING,
    CONF_LOG_LEVEL,
    CONF_LOG_VERSION_PREFIX,
    DEFAULT_ADVANCED_LOGGING,
    DEFAULT_LOG_LEVEL,
    DEFAULT_LOG_VERSION_PREFIX,
    DOMAIN,
    ENTITY_DETAIL_LOGGER_NAME,
    HEURISTICS_LOGGER_NAME,
    LIFECYCLE_LOGGER_NAME,
    PROCESSOR_LOGGER_NAME,
    USER_ACTION_LOGGER_NAME,
)

__all__ = [
    "configure_loggers",
    "format_for_log",
    "make_log_prefix",
    "AdvancedLoggingFilter",
    "HdgVersionFilter",
    "set_version_prefix_enabled",
    "_LOGGER",
    "_LIFECYCLE_LOGGER",
    "_ENTITY_DETAIL_LOGGER",
    "_API_LOGGER",
    "_HEURISTICS_LOGGER",
    "_PROCESSOR_LOGGER",
    "_USER_ACTION_LOGGER",
]

try:
    _INTEGRATION_VERSION: str = json.loads(
        (Path(__file__).parent.parent / "manifest.json").read_text()
    ).get("version", "unknown")
except Exception:
    _INTEGRATION_VERSION = "unknown"

_VERSION_PREFIX_ENABLED: bool = DEFAULT_LOG_VERSION_PREFIX
_VERSION_PREFIX: str = f"[v{_INTEGRATION_VERSION}] "

_LOGGER = logging.getLogger(DOMAIN)
_LIFECYCLE_LOGGER = logging.getLogger(LIFECYCLE_LOGGER_NAME)
_ENTITY_DETAIL_LOGGER = logging.getLogger(ENTITY_DETAIL_LOGGER_NAME)
_API_LOGGER = logging.getLogger(API_LOGGER_NAME)
_HEURISTICS_LOGGER = logging.getLogger(HEURISTICS_LOGGER_NAME)
_PROCESSOR_LOGGER = logging.getLogger(PROCESSOR_LOGGER_NAME)
_USER_ACTION_LOGGER = logging.getLogger(USER_ACTION_LOGGER_NAME)

_SPAMMY_LOGGERS = [
    _ENTITY_DETAIL_LOGGER,
    _API_LOGGER,
    _LIFECYCLE_LOGGER,
    _HEURISTICS_LOGGER,
    _PROCESSOR_LOGGER,
    _USER_ACTION_LOGGER,
]
_SPAMMY_LOGGER_NAMES = {logger.name for logger in _SPAMMY_LOGGERS}


class HdgVersionFilter(logging.Filter):
    """Prepend integration version to every log message when enabled."""

    def filter(self, record: logging.LogRecord) -> bool:
        """Prepend version tag to the log message."""
        if _VERSION_PREFIX_ENABLED and isinstance(record.msg, str):
            record.msg = _VERSION_PREFIX + record.msg
        return True


def set_version_prefix_enabled(enabled: bool) -> None:
    """Enable or disable version prefix injection in log messages."""
    global _VERSION_PREFIX_ENABLED
    _VERSION_PREFIX_ENABLED = enabled


class AdvancedLoggingFilter(logging.Filter):
    """A logging filter that suppresses messages from specific 'spammy' loggers.

    This filter checks if the 'advanced_logging' option is enabled in the ConfigEntry.
    If it's disabled, any log record from a logger in _SPAMMY_LOGGER_NAMES will be suppressed.
    """

    def __init__(self, entry: ConfigEntry) -> None:
        """Initialize the filter with the config entry."""
        super().__init__()
        self.is_advanced = bool(
            entry.options.get(CONF_ADVANCED_LOGGING, DEFAULT_ADVANCED_LOGGING)
        )

    def filter(self, record: logging.LogRecord) -> bool:
        """Filter log records based on the advanced logging setting."""
        return True if self.is_advanced else record.name not in _SPAMMY_LOGGER_NAMES


def format_for_log(obj: Any, max_len: int = 150) -> str:
    """Format an object for logging, truncating it if it is too long."""
    try:
        s = str(obj)
    except Exception:
        return f"(un-string-able object of type {type(obj).__name__})"

    return f"{s[: max_len - 3]}..." if len(s) > max_len else s


def make_log_prefix(node_id: str | None, entity_name: str | None) -> str:
    """Create a consistent log prefix for a given node ID and entity name."""
    parts = [f"[{part}]" for part in (entity_name, node_id) if part]
    return "".join(parts) + " " if parts else ""


def configure_loggers(entry: ConfigEntry) -> None:
    """Set up the integration's loggers based on user configuration."""
    log_level_str = entry.options.get(CONF_LOG_LEVEL, DEFAULT_LOG_LEVEL).upper()
    log_level = getattr(logging, log_level_str, logging.INFO)
    is_advanced = bool(
        entry.options.get(CONF_ADVANCED_LOGGING, DEFAULT_ADVANCED_LOGGING)
    )
    version_prefix = bool(
        entry.options.get(CONF_LOG_VERSION_PREFIX, DEFAULT_LOG_VERSION_PREFIX)
    )

    set_version_prefix_enabled(version_prefix)

    advanced_filter = AdvancedLoggingFilter(entry)
    version_filter = HdgVersionFilter()

    all_loggers = [_LOGGER] + _SPAMMY_LOGGERS
    for logger in all_loggers:
        logger.setLevel(log_level)
        # Remove any existing filters to prevent duplication on reload
        logger.filters.clear()
        logger.addFilter(version_filter)
        if logger in _SPAMMY_LOGGERS:
            logger.addFilter(advanced_filter)
        # Ensure logs are passed up to the parent Home Assistant logger
        logger.propagate = True

    _LOGGER.info(
        "HDG Bavaria Boiler integration log level set to '%s'. Advanced logging is %s.",
        log_level_str,
        "ON" if is_advanced else "OFF",
    )
