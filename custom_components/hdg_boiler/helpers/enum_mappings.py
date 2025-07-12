"""Mappings for converting HDG boiler enum text values to canonical keys.

This module defines dictionaries that map the human-readable text values
returned by the HDG boiler API for enumerated types to their corresponding
canonical keys used internally by the integration and in Home Assistant's
translation files. This is crucial for robust parsing and setting of enum
values, ensuring consistency between the API's output and the integration's
internal representation.
"""

from typing import Final

HDG_ENUM_TEXT_TO_KEY_MAPPINGS: Final[dict[str, dict[str, str]]] = {
    "betriebsart": {
        "Normal": "NORMAL",
        "Tagbetrieb": "TAG",
        "Nachtbetrieb": "NACHT",
        "Partybetrieb": "PARTY",
        "Sommer­betrieb": "SOMMER",
    },
}
