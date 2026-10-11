"""Logging utility functions for the HDG Bavaria Boiler integration."""

from __future__ import annotations

import json
import logging
import re
import threading
import traceback
from pathlib import Path
from typing import Any
from urllib.parse import quote, urlparse

from homeassistant.config_entries import ConfigEntry

from ..const import (
    API_LOGGER_NAME,
    CONF_ADVANCED_LOGGING,
    CONF_HOST_IP,
    CONF_LOG_LEVEL,
    CONF_LOG_VERSION_PREFIX,
    DEFAULT_ADVANCED_LOGGING,
    DEFAULT_LOG_LEVEL,
    DEFAULT_LOG_VERSION_PREFIX,
    DIAGNOSTICS_REDACTED_PLACEHOLDER,
    DOMAIN,
    ENTITY_DETAIL_LOGGER_NAME,
    HEURISTICS_LOGGER_NAME,
    LIFECYCLE_LOGGER_NAME,
    PROCESSOR_LOGGER_NAME,
    USER_ACTION_LOGGER_NAME,
)

__all__ = [
    "INTEGRATION_VERSION",
    "configure_loggers",
    "format_for_log",
    "get_redacted_logger",
    "make_log_prefix",
    "note_host_secret",
    "note_log_secret",
    "redact",
    "AdvancedLoggingFilter",
    "HdgRedactionFilter",
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
    INTEGRATION_VERSION = json.loads(
        (Path(__file__).parent.parent / "manifest.json").read_text()
    ).get("version", "unknown")
except Exception:
    INTEGRATION_VERSION = "unknown"

# Values shorter than this would hide ordinary words ("Tag", "Aus", node ids).
_MIN_SECRET_LENGTH = 4
_SECRET_SKIP = frozenset(
    {
        DIAGNOSTICS_REDACTED_PLACEHOLDER.casefold(),
        "redacted",
        "**redacted**",
        "unknown",
        "none",
        "null",
        "unavailable",
        "n/a",
        "---",
    }
)
# Anlagenbezeichnung (20026) and MAC (20031), in either JSON field order.
_SENSITIVE_NODE_IDS = frozenset({"20026", "20026t", "20031", "20031t"})
_SENSITIVE_NODE_TEXT_RE = re.compile(
    r'"(?P<k1>id|text)"\s*:\s*"(?P<v1>(?:\\.|[^"\\])*)"'
    r"[^}]{0,300}?"
    r'"(?P<k2>id|text)"\s*:\s*"(?P<v2>(?:\\.|[^"\\])*)"',
    re.IGNORECASE,
)
_MAC_RE = re.compile(
    r"(?i)(?<![A-Za-z0-9])(?:[0-9a-f]{2}[:-]){5}[0-9a-f]{2}(?![A-Za-z0-9])"
)

_secrets_lock = threading.Lock()
_log_secrets: dict[str, re.Pattern[str]] = {}

_VERSION_PREFIX_ENABLED: bool = DEFAULT_LOG_VERSION_PREFIX
_VERSION_PREFIX: str = f"[v{INTEGRATION_VERSION}] "
_CURRENT_INTEGRATION_LOG_LEVEL: int | None = None

_LOGGER: logging.Logger
_LIFECYCLE_LOGGER: logging.Logger
_ENTITY_DETAIL_LOGGER: logging.Logger
_API_LOGGER: logging.Logger
_HEURISTICS_LOGGER: logging.Logger
_PROCESSOR_LOGGER: logging.Logger
_USER_ACTION_LOGGER: logging.Logger


def _is_integration_logger(name: str) -> bool:
    """Return True for this integration's logger names.

    Filters do not propagate to child loggers, so both the ``hdg_boiler`` tree
    and ``custom_components.hdg_boiler`` (module ``__name__`` loggers) need them.
    """
    package = f"custom_components.{DOMAIN}"
    return (
        name == DOMAIN
        or name.startswith(f"{DOMAIN}.")
        or name == package
        or name.startswith(f"{package}.")
    )


def _secret_variants(text: str) -> set[str]:
    """Forms a secret can take in logs, unique ids, and entity ids."""
    variants = {text}
    quoted = quote(text, safe="")
    if quoted != text:
        variants.add(quoted)
    if slugged := re.sub(r"[^A-Za-z0-9]+", "_", text).strip("_"):
        variants.add(slugged)
    return {
        variant
        for variant in variants
        if len(variant) >= _MIN_SECRET_LENGTH and variant.casefold() not in _SECRET_SKIP
    }


def _compile_secret(secret: str) -> re.Pattern[str]:
    """Match a secret as its own token, including inside ``::`` and ``_`` ids."""
    return re.compile(
        rf"(?<![A-Za-z0-9]){re.escape(secret)}(?![A-Za-z0-9])",
        re.IGNORECASE,
    )


def note_log_secret(value: Any) -> None:
    """Remember a concrete serial, MAC, or host seen at runtime.

    The value stays hidden for the rest of the process. Temperatures, modes,
    and other boiler data are never registered here.
    """
    if value is None or isinstance(value, bool | int | float):
        return
    text = str(value).strip()
    if len(text) < _MIN_SECRET_LENGTH or text.casefold() in _SECRET_SKIP:
        return

    with _secrets_lock:
        for variant in _secret_variants(text):
            if variant not in _log_secrets:
                _log_secrets[variant] = _compile_secret(variant)


def note_host_secret(value: Any) -> None:
    """Remember a boiler host, including the hostname parsed out of a URL."""
    if not isinstance(value, str):
        return
    note_log_secret(value)
    candidate = value.strip()
    if not candidate:
        return
    parsed = urlparse(candidate if "://" in candidate else f"//{candidate}")
    if parsed.hostname:
        note_log_secret(parsed.hostname)


def _note_secrets_in_node_payload(data: str) -> None:
    """Pull Anlagenbezeichnung and MAC out of a raw node JSON fragment."""
    if "20026" not in data and "20031" not in data:
        return
    for match in _SENSITIVE_NODE_TEXT_RE.finditer(data):
        fields = {
            match.group("k1").casefold(): match.group("v1"),
            match.group("k2").casefold(): match.group("v2"),
        }
        node_id = fields.get("id", "")
        if "text" in fields and node_id.casefold() in _SENSITIVE_NODE_IDS:
            note_log_secret(fields["text"])


def _replace_noted_secrets(data: str) -> str:
    """Replace every registered secret in ``data``."""
    with _secrets_lock:
        patterns = [
            pattern
            for _, pattern in sorted(
                _log_secrets.items(), key=lambda item: len(item[0]), reverse=True
            )
        ]
    for pattern in patterns:
        data = pattern.sub(DIAGNOSTICS_REDACTED_PLACEHOLDER, data)
    return data


def redact(data: Any) -> Any:
    """Redact serial, MAC, and host values in a string. Other types pass through."""
    if isinstance(data, Exception):
        return redact(str(data))
    if not isinstance(data, str) or not data:
        return data

    _note_secrets_in_node_payload(data)
    data = _replace_noted_secrets(data)
    return _MAC_RE.sub(DIAGNOSTICS_REDACTED_PLACEHOLDER, data)


class HdgVersionFilter(logging.Filter):
    """Prepend integration version to every log message when enabled."""

    def filter(self, record: logging.LogRecord) -> bool:
        """Prepend version tag to the log message."""
        if (
            _VERSION_PREFIX_ENABLED
            and isinstance(record.msg, str)
            and not record.msg.startswith(_VERSION_PREFIX)
        ):
            record.msg = _VERSION_PREFIX + record.msg
        return True


def _redact_record(record: logging.LogRecord) -> None:
    """Redact the rendered line and any traceback attached to it."""
    if record.args:
        try:
            rendered = record.getMessage()
        except Exception:
            rendered = str(record.msg)
        record.msg = redact(rendered)
        record.args = ()
    elif isinstance(record.msg, str):
        record.msg = redact(record.msg)

    if record.exc_info and not record.exc_text:
        record.exc_text = redact("".join(traceback.format_exception(*record.exc_info)))
        record.exc_info = None
    elif isinstance(record.exc_text, str):
        record.exc_text = redact(record.exc_text)

    if isinstance(record.stack_info, str):
        record.stack_info = redact(record.stack_info)


class HdgRedactionFilter(logging.Filter):
    """Hide serial, MAC, and host values on the way out of a log record."""

    def filter(self, record: logging.LogRecord) -> bool:
        """Redact the rendered message, its arguments, and the traceback."""
        _redact_record(record)
        return True


def set_version_prefix_enabled(enabled: bool) -> None:
    """Enable or disable version prefix injection in log messages."""
    global _VERSION_PREFIX_ENABLED
    _VERSION_PREFIX_ENABLED = enabled


def _ensure_record_filters(logger: logging.Logger) -> None:
    """Attach version and redaction filters once. They do not inherit."""
    existing = {type(item) for item in logger.filters}
    if HdgVersionFilter not in existing:
        logger.addFilter(HdgVersionFilter())
    if HdgRedactionFilter not in existing:
        logger.addFilter(HdgRedactionFilter())


def get_redacted_logger(name: str) -> logging.Logger:
    """Return a logger with version and redaction filters attached."""
    logger = logging.getLogger(name)
    _ensure_record_filters(logger)
    if _CURRENT_INTEGRATION_LOG_LEVEL is not None and _is_integration_logger(name):
        logger.setLevel(_CURRENT_INTEGRATION_LOG_LEVEL)
    return logger


_LOGGER = get_redacted_logger(DOMAIN)
_LIFECYCLE_LOGGER = get_redacted_logger(LIFECYCLE_LOGGER_NAME)
_ENTITY_DETAIL_LOGGER = get_redacted_logger(ENTITY_DETAIL_LOGGER_NAME)
_API_LOGGER = get_redacted_logger(API_LOGGER_NAME)
_HEURISTICS_LOGGER = get_redacted_logger(HEURISTICS_LOGGER_NAME)
_PROCESSOR_LOGGER = get_redacted_logger(PROCESSOR_LOGGER_NAME)
_USER_ACTION_LOGGER = get_redacted_logger(USER_ACTION_LOGGER_NAME)

_SPAMMY_LOGGERS = [
    _ENTITY_DETAIL_LOGGER,
    _API_LOGGER,
    _LIFECYCLE_LOGGER,
    _HEURISTICS_LOGGER,
    _PROCESSOR_LOGGER,
    _USER_ACTION_LOGGER,
]
_SPAMMY_LOGGER_NAMES = {logger.name for logger in _SPAMMY_LOGGERS}


class AdvancedLoggingFilter(logging.Filter):
    """Suppress messages from specific 'spammy' loggers unless advanced logging is on."""

    def __init__(self, entry: ConfigEntry) -> None:
        """Initialize the filter with the config entry."""
        super().__init__()
        self.is_advanced = bool(
            entry.options.get(CONF_ADVANCED_LOGGING, DEFAULT_ADVANCED_LOGGING)
        )

    def filter(self, record: logging.LogRecord) -> bool:
        """Filter log records based on the advanced logging setting."""
        return True if self.is_advanced else record.name not in _SPAMMY_LOGGER_NAMES


_MANAGED_FILTERS = (AdvancedLoggingFilter, HdgVersionFilter, HdgRedactionFilter)


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


def _integration_logger_names() -> set[str]:
    """Collect integration loggers that already exist, plus the known names."""
    names = {DOMAIN, f"custom_components.{DOMAIN}"}
    names.update(logger.name for logger in _SPAMMY_LOGGERS)
    for name in list(logging.root.manager.loggerDict):
        if _is_integration_logger(name):
            names.add(name)
    return names


def configure_loggers(entry: ConfigEntry) -> None:
    """Set up the integration's loggers based on user configuration."""
    global _CURRENT_INTEGRATION_LOG_LEVEL

    log_level_str = entry.options.get(CONF_LOG_LEVEL, DEFAULT_LOG_LEVEL).upper()
    log_level = getattr(logging, log_level_str, logging.INFO)
    is_advanced = bool(
        entry.options.get(CONF_ADVANCED_LOGGING, DEFAULT_ADVANCED_LOGGING)
    )
    version_prefix = bool(
        entry.options.get(CONF_LOG_VERSION_PREFIX, DEFAULT_LOG_VERSION_PREFIX)
    )

    set_version_prefix_enabled(version_prefix)
    _CURRENT_INTEGRATION_LOG_LEVEL = log_level
    note_host_secret(entry.data.get(CONF_HOST_IP))

    advanced_filter = AdvancedLoggingFilter(entry)
    for name in _integration_logger_names():
        logger = get_redacted_logger(name)
        logger.setLevel(log_level)
        logger.filters[:] = [
            item for item in logger.filters if not isinstance(item, _MANAGED_FILTERS)
        ]
        if name in _SPAMMY_LOGGER_NAMES:
            logger.addFilter(advanced_filter)
        logger.addFilter(HdgVersionFilter())
        logger.addFilter(HdgRedactionFilter())
        logger.propagate = True

    _LOGGER.info(
        "HDG Bavaria Boiler integration log level set to '%s'. Advanced logging is %s.",
        log_level_str,
        "ON" if is_advanced else "OFF",
    )
