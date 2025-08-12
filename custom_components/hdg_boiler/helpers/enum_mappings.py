"""Mappings for converting HDG boiler enum text values to canonical keys.

This module defines dictionaries that map the human-readable text values
returned by the HDG boiler API for enumerated types to their corresponding
canonical keys used internally by the integration and in Home Assistant's
translation files.
"""

from __future__ import annotations

__version__ = "0.1.0"

from typing import Final

__all__ = ["HDG_ENUM_TEXT_TO_KEY_MAPPINGS"]

HDG_ENUM_TEXT_TO_KEY_MAPPINGS: Final[dict[str, dict[str, str]]] = {
    "betriebsart": {
        "Normal": "NORMAL",
        "Tagbetrieb": "TAG",
        "Nachtbetrieb": "NACHT",
        "Partybetrieb": "PARTY",
        "Sommer­betrieb": "SOMMER",
    },
}
