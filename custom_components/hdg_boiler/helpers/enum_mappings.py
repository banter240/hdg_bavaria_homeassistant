"""Mappings for converting HDG boiler enum text values to canonical keys.

This module defines dictionaries that map the human-readable text values
returned by the HDG boiler API for enumerated types to their corresponding
canonical keys used internally by the integration and in Home Assistant's
translation files.
"""

from __future__ import annotations


from typing import Final

__all__ = ["HDG_ENUM_TEXT_TO_KEY_MAPPINGS"]

HDG_ENUM_TEXT_TO_KEY_MAPPINGS: Final[dict[str, dict[str, str]]] = {
    "hk1_betriebsart": {
        "Normal": "NORMAL",
        "Tagbetrieb": "TAG",
        "Nachtbetrieb": "NACHT",
        "Partybetrieb": "PARTY",
        "Sommer- betrieb": "SOMMER",
    },
    "hk2_betriebsart": {
        "Normal": "NORMAL",
        "Tagbetrieb": "TAG",
        "Nachtbetrieb": "NACHT",
        "Partybetrieb": "PARTY",
        "Sommer- betrieb": "SOMMER",
    },
    "hk3_betriebsart": {
        "Normal": "NORMAL",
        "Tagbetrieb": "TAG",
        "Nachtbetrieb": "NACHT",
        "Partybetrieb": "PARTY",
        "Sommer- betrieb": "SOMMER",
    },
    "hk4_betriebsart": {
        "Normal": "NORMAL",
        "Tagbetrieb": "TAG",
        "Nachtbetrieb": "NACHT",
        "Partybetrieb": "PARTY",
        "Sommer- betrieb": "SOMMER",
    },
    "hk5_betriebsart": {
        "Normal": "NORMAL",
        "Tagbetrieb": "TAG",
        "Nachtbetrieb": "NACHT",
        "Partybetrieb": "PARTY",
        "Sommer- betrieb": "SOMMER",
    },
    "hk6_betriebsart": {
        "Normal": "NORMAL",
        "Tagbetrieb": "TAG",
        "Nachtbetrieb": "NACHT",
        "Partybetrieb": "PARTY",
        "Sommer- betrieb": "SOMMER",
    },
    "hk1_aktuelle_betriebsart": {
        "Abgesenkt": "abgesenkt",
        "Aus": "aus",
        "Standard": "standard",
        "Tagbetrieb": "tag",
        "Nachtbetrieb": "nacht",
        "Partybetrieb": "party",
        "Urlaubs- betrieb": "urlaub",
        "Sommer- betrieb": "sommer",
    },
    "hk2_aktuelle_betriebsart": {
        "Abgesenkt": "abgesenkt",
        "Aus": "aus",
        "Standard": "standard",
        "Tagbetrieb": "tag",
        "Nachtbetrieb": "nacht",
        "Partybetrieb": "party",
        "Urlaubs- betrieb": "urlaub",
        "Sommer- betrieb": "sommer",
    },
    "hk3_aktuelle_betriebsart": {
        "Abgesenkt": "abgesenkt",
        "Aus": "aus",
        "Standard": "standard",
        "Tagbetrieb": "tag",
        "Nachtbetrieb": "nacht",
        "Partybetrieb": "party",
        "Urlaubs- betrieb": "urlaub",
        "Sommer- betrieb": "sommer",
    },
    "hk4_aktuelle_betriebsart": {
        "Abgesenkt": "abgesenkt",
        "Aus": "aus",
        "Standard": "standard",
        "Tagbetrieb": "tag",
        "Nachtbetrieb": "nacht",
        "Partybetrieb": "party",
        "Urlaubs- betrieb": "urlaub",
        "Sommer- betrieb": "sommer",
    },
    "hk5_aktuelle_betriebsart": {
        "Abgesenkt": "abgesenkt",
        "Aus": "aus",
        "Standard": "standard",
        "Tagbetrieb": "tag",
        "Nachtbetrieb": "nacht",
        "Partybetrieb": "party",
        "Urlaubs- betrieb": "urlaub",
        "Sommer- betrieb": "sommer",
    },
    "hk6_aktuelle_betriebsart": {
        "Abgesenkt": "abgesenkt",
        "Aus": "aus",
        "Standard": "standard",
        "Tagbetrieb": "tag",
        "Nachtbetrieb": "nacht",
        "Partybetrieb": "party",
        "Urlaubs- betrieb": "urlaub",
        "Sommer- betrieb": "sommer",
    },
    "anlage_betriebsart": {
        "Normal": "normal",
        "Urlaubs- betrieb": "urlaubs_betrieb",
        "Sommer- betrieb": "sommerbetrieb",
        "Frostschutz": "frostschutz",
    },
    "externe_warmequelle_betriebsart": {
        "AUS": "aus",
        "EIN": "ein",
        "AUTO_EIN": "auto_ein",
        "AUTO_AUS": "auto_aus",
        "Aus": "aus",
        "Ein": "ein",
        "Auto": "auto_ein",
    },
}
