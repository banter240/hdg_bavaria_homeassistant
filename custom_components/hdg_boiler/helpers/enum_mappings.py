"""Mappings for converting HDG boiler enum text values to canonical keys.

This module defines dictionaries that map the human-readable text values
returned by the HDG boiler API for enumerated types to their corresponding
canonical keys used internally by the integration and in Home Assistant's
translation files.
"""

from __future__ import annotations

import re
from typing import Final

__all__ = ["HDG_ENUM_TEXT_TO_KEY_MAPPINGS", "resolve_hdg_enum_key"]

# Touch labels wrap long words as "Sommer-\r\nbetrieb". Polls also arrive as
# "Sommer- betrieb", "Sommer-betrieb", or with a <br> tag.
_BR_TAG_RE = re.compile(r"(?i)<br\s*/?>")
_WHITESPACE_RE = re.compile(r"\s+")
_HYPHEN_BREAK_RE = re.compile(r"-\s*")
_DASH_RE = re.compile(r"[\u00ad\u2010\u2011\u2012\u2013\u2014\u2212]")


def _fold_hdg_enum_text(value: str) -> str:
    """Collapse line breaks so wrapped HDG labels compare equal."""
    text = _DASH_RE.sub("-", value)
    text = _BR_TAG_RE.sub(" ", text)
    text = text.replace("\r", " ").replace("\n", " ")
    return _WHITESPACE_RE.sub(" ", text).strip().casefold()


def _compact_hdg_enum_text(value: str) -> str:
    """Drop a line-break hyphen: 'Sommer- betrieb' and 'Sommerbetrieb' match."""
    return _HYPHEN_BREAK_RE.sub("", _fold_hdg_enum_text(value))


def resolve_hdg_enum_key(raw_value: str, enum_map: dict[str, str]) -> str | None:
    """Return the canonical key for a raw HDG enum label, if one is known."""
    folded = _fold_hdg_enum_text(raw_value)
    compact = _compact_hdg_enum_text(raw_value)
    return next(
        (
            key
            for text, key in enum_map.items()
            if (
                _fold_hdg_enum_text(text) == folded
                or _compact_hdg_enum_text(text) == compact
                or key.casefold() == folded
            )
        ),
        None,
    )


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
    "solar_system_auswahl": {
        "1 Zone": "1_zone",
        "2 Zonen": "2_zonen",
        "3 Zonen": "3_zonen",
    },
    "solar_zone_1": {
        "Puffer 1 oben": "puffer_1_oben",
        "Puffer 1 mitte-oben": "puffer_1_mitte_oben",
        "Puffer 1 mitte": "puffer_1_mitte",
        "Puffer 1 mitte-unten": "puffer_1_mitte_unten",
        "Puffer 1 unten": "puffer_1_unten",
        "Puffer 2 oben": "puffer_2_oben",
        "Puffer 2 mitte-oben": "puffer_2_mitte_oben",
        "Puffer 2 mitte": "puffer_2_mitte",
        "Puffer 2 mitte-unten": "puffer_2_mitte_unten",
        "Puffer 2 unten": "puffer_2_unten",
        "Brauchwasser 1 unten": "brauchwasser_1_unten",
        "Brauchwasser 2 unten": "brauchwasser_2_unten",
    },
    "solar_zone_2": {
        "Puffer 1 oben": "puffer_1_oben",
        "Puffer 1 mitte-oben": "puffer_1_mitte_oben",
        "Puffer 1 mitte": "puffer_1_mitte",
        "Puffer 1 mitte-unten": "puffer_1_mitte_unten",
        "Puffer 1 unten": "puffer_1_unten",
        "Puffer 2 oben": "puffer_2_oben",
        "Puffer 2 mitte-oben": "puffer_2_mitte_oben",
        "Puffer 2 mitte": "puffer_2_mitte",
        "Puffer 2 mitte-unten": "puffer_2_mitte_unten",
        "Puffer 2 unten": "puffer_2_unten",
        "Brauchwasser 1 unten": "brauchwasser_1_unten",
        "Brauchwasser 2 unten": "brauchwasser_2_unten",
    },
    "solar_zone_3": {
        "Puffer 1 oben": "puffer_1_oben",
        "Puffer 1 mitte-oben": "puffer_1_mitte_oben",
        "Puffer 1 mitte": "puffer_1_mitte",
        "Puffer 1 mitte-unten": "puffer_1_mitte_unten",
        "Puffer 1 unten": "puffer_1_unten",
        "Puffer 2 oben": "puffer_2_oben",
        "Puffer 2 mitte-oben": "puffer_2_mitte_oben",
        "Puffer 2 mitte": "puffer_2_mitte",
        "Puffer 2 mitte-unten": "puffer_2_mitte_unten",
        "Puffer 2 unten": "puffer_2_unten",
        "Brauchwasser 1 unten": "brauchwasser_1_unten",
        "Brauchwasser 2 unten": "brauchwasser_2_unten",
    },
    "solar_invertierung_ventil_1_aktivieren": {
        "Ja": "ja",
        "Nein": "nein",
    },
    "solar_invertierung_ventil_2_aktivieren": {
        "Ja": "ja",
        "Nein": "nein",
    },
    "solar_solaranlage": {
        "KEINE": "keine",
        "BRAUCHWASSER": "brauchwasser",
        "PUFFER": "puffer",
        "BRAUCHWASSER-PUFFER": "brauchwasser_puffer",
        "BRAUCHWASSER-WT-PUFFER": "brauchwasser_wt_puffer",
    },
}
