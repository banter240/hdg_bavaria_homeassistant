#!/usr/bin/env python3
"""Check consistency between per-circuit translation blocks and Python sources.

The translation files contain repeated per-circuit state blocks (HK1-HK6
betriebsart selects, HK1-HK6 aktuelle_betriebsart sensors, solar zones 1-3,
solar valve inversion 1/2). Home Assistant loads translations statically, so
the duplication is inherent, but drift against helpers/enum_mappings.py and
definitions.py is invisible at runtime.

The Python sources are parsed with ast instead of imported because they pull
in homeassistant; this keeps the script pure standard library for CI.

Extras in the state blocks beyond the enum map values are tolerated (reported
as notes, not errors): the maps only cover labels the firmware currently
sends, while translations intentionally cover more (e.g. the hk*_betriebsart
select carries a holiday state the boiler can report but the options omit).
Missing states are always errors: an unmapped-or-untranslated state would
surface as a raw key in the UI.
"""

from __future__ import annotations

import ast
import json
import sys
from pathlib import Path
from typing import Any, cast

TRANSLATION_PATHS = {
    lang: Path(f"custom_components/hdg_boiler/translations/{lang}.json")
    for lang in ("en", "de")
}
ENUM_MAPPINGS_PATH = Path("custom_components/hdg_boiler/helpers/enum_mappings.py")
DEFINITIONS_PATH = Path("custom_components/hdg_boiler/definitions.py")

# platform, key template, circuit indexes, enum map source name in
# enum_mappings.py.
FAMILIES = [
    ("select", "hk{n}_betriebsart", range(1, 7), "_HK_BETRIEBSART"),
    (
        "sensor",
        "hk{n}_aktuelle_betriebsart",
        range(1, 7),
        "_HK_AKTUELLE_BETRIEBSART",
    ),
    ("sensor", "solar_zone_{n}", range(1, 4), "_SOLAR_ZONE_ZUORDNUNG"),
    (
        "sensor",
        "solar_invertierung_ventil_{n}_aktivieren",
        range(1, 3),
        "_JA_NEIN",
    ),
]

# select options constant in definitions.py, representative select key, and
# the enum map feeding the same states (a module-level dict in
# enum_mappings.py, or a plain entry of HDG_ENUM_TEXT_TO_KEY_MAPPINGS).
SELECT_OPTION_SETS = [
    ("HK_OPERATING_MODE_OPTIONS", "hk1_betriebsart", "_HK_BETRIEBSART"),
    (
        "EXT_WQ_OPERATING_MODE_OPTIONS",
        "externe_warmequelle_betriebsart",
        "externe_warmequelle_betriebsart",
    ),
]


def _assigned_literal(source: str, name: str) -> Any:
    """Return the literal value of a module-level assignment, or None."""
    for node in ast.walk(ast.parse(source)):
        targets: list[ast.expr]
        if isinstance(node, ast.Assign):
            targets = node.targets
        elif isinstance(node, ast.AnnAssign):
            targets = [node.target]
        else:
            continue
        if not any(
            isinstance(target, ast.Name) and target.id == name for target in targets
        ):
            continue
        if node.value is None:
            return None
        try:
            return ast.literal_eval(node.value)
        except (ValueError, SyntaxError):
            return None
    return None


def _mapping_entry(source: str, entry: str) -> dict[str, str] | None:
    """Extract a plain-dict entry from the HDG_ENUM_TEXT_TO_KEY_MAPPINGS display.

    Returns None when the entry is missing or not a plain dict literal, so
    callers can fail with a clear message instead of guessing.
    """
    for node in ast.walk(ast.parse(source)):
        targets: list[ast.expr]
        if isinstance(node, ast.Assign):
            targets = node.targets
        elif isinstance(node, ast.AnnAssign):
            targets = [node.target]
        else:
            continue
        if not any(
            isinstance(target, ast.Name)
            and target.id == "HDG_ENUM_TEXT_TO_KEY_MAPPINGS"
            for target in targets
        ):
            continue
        if not isinstance(node.value, ast.Dict):
            return None
        for key_node, value_node in zip(node.value.keys, node.value.values):
            if (
                isinstance(key_node, ast.Constant)
                and key_node.value == entry
                and isinstance(value_node, ast.Dict)
            ):
                result: dict[str, str] = ast.literal_eval(value_node)
                return result
        return None
    return None


def _load_json(path: Path, errors: list[str]) -> dict[str, Any] | None:
    try:
        with path.open(encoding="utf-8") as file:
            return cast(dict[str, Any], json.load(file))
    except (OSError, json.JSONDecodeError) as exc:
        errors.append(f"{path}: cannot load: {exc}")
        return None


def _read_source(path: Path, errors: list[str]) -> str | None:
    try:
        return path.read_text(encoding="utf-8")
    except OSError as exc:
        errors.append(f"{path}: cannot read: {exc}")
        return None


def _state_block(
    translation: dict[str, Any],
    path: Path,
    platform: str,
    key: str,
    errors: list[str],
) -> dict[str, str] | None:
    """Return the state block of an entity, recording an error if absent."""
    try:
        block = translation["entity"][platform][key]["state"]
    except (KeyError, TypeError):
        errors.append(f"{path}: missing entity.{platform}.{key}.state")
        return None
    if not isinstance(block, dict):
        errors.append(f"{path}: entity.{platform}.{key}.state is not an object")
        return None
    return {str(state_key): str(label) for state_key, label in block.items()}


def _describe_drift(reference: dict[str, str], other: dict[str, str]) -> str:
    """Summarize how two state blocks differ (for error messages)."""
    parts = []
    if missing := sorted(set(reference) - set(other)):
        parts.append(f"missing keys {missing}")
    if extra := sorted(set(other) - set(reference)):
        parts.append(f"extra keys {extra}")
    if relabeled := sorted(
        state_key
        for state_key in set(reference) & set(other)
        if reference[state_key] != other[state_key]
    ):
        parts.append(f"different labels {relabeled}")
    return "; ".join(parts)


def check_family_copies(
    translations: dict[str, dict[str, Any]], errors: list[str]
) -> dict[tuple[str, str], dict[str, dict[str, str]]]:
    """Verify per-circuit copies are identical within and across languages.

    Labels differ between languages by design, so only the key sets are
    compared across languages. Returns the per-language reference block of
    each family for the follow-up checks against the Python sources.
    """
    references: dict[tuple[str, str], dict[str, dict[str, str]]] = {}
    for platform, template, indexes, _map_name in FAMILIES:
        family_ref: dict[str, dict[str, str]] = {}
        first_key = template.format(n=next(iter(indexes)))
        for lang, path in TRANSLATION_PATHS.items():
            reference = _state_block(
                translations[lang], path, platform, first_key, errors
            )
            if reference is None:
                continue
            family_ref[lang] = reference
            for index in indexes:
                if index == next(iter(indexes)):
                    continue
                key = template.format(n=index)
                block = _state_block(translations[lang], path, platform, key, errors)
                if block is not None and block != reference:
                    errors.append(
                        f"{path}: entity.{platform}.{key}.state drifted from "
                        f"entity.{platform}.{first_key}.state "
                        f"({_describe_drift(reference, block)})"
                    )
        if "en" in family_ref and "de" in family_ref:
            en_keys = set(family_ref["en"])
            de_keys = set(family_ref["de"])
            if en_keys != de_keys:
                errors.append(
                    f"{TRANSLATION_PATHS['en']} vs {TRANSLATION_PATHS['de']}: "
                    f"entity.{platform}.{first_key}.state key sets differ "
                    f"({_describe_drift(family_ref['en'], family_ref['de'])})"
                )
        references[(platform, template)] = family_ref
    return references


def _enum_map(
    enum_source: str, map_name: str, errors: list[str]
) -> dict[str, str] | None:
    """Resolve an enum map by module-level name or mappings entry."""
    assigned = _assigned_literal(enum_source, map_name)
    if isinstance(assigned, dict):
        return {str(text): str(key) for text, key in assigned.items()}
    entry = _mapping_entry(enum_source, map_name)
    if entry is not None:
        return entry
    errors.append(
        f"{ENUM_MAPPINGS_PATH}: enum map '{map_name}' not found or not a plain literal"
    )
    return None


def check_enum_coverage(
    references: dict[tuple[str, str], dict[str, dict[str, str]]],
    enum_source: str,
    errors: list[str],
    notes: list[str],
) -> None:
    """Require every enum map value to have a matching translation state."""
    for platform, template, indexes, map_name in FAMILIES:
        enum_map = _enum_map(enum_source, map_name, errors)
        if enum_map is None:
            continue
        map_values = {str(value).lower() for value in enum_map.values()}
        first_key = template.format(n=next(iter(indexes)))
        for lang, path in TRANSLATION_PATHS.items():
            reference = references.get((platform, template), {}).get(lang)
            if reference is None:
                continue
            if missing := sorted(map_values - set(reference)):
                errors.append(
                    f"{path}: entity.{platform}.{first_key}.state is missing "
                    f"states {missing} produced by {map_name}"
                )
            if extra := sorted(set(reference) - map_values):
                notes.append(
                    f"{path}: entity.{platform}.{first_key}.state has extra "
                    f"states {extra} beyond {map_name} (tolerated)"
                )


def check_select_options(
    definitions_source: str,
    enum_source: str,
    references: dict[tuple[str, str], dict[str, dict[str, str]]],
    errors: list[str],
) -> None:
    """Require select options to match the enum map values and translations."""
    for options_name, select_key, map_name in SELECT_OPTION_SETS:
        options = _assigned_literal(definitions_source, options_name)
        if not isinstance(options, list):
            errors.append(
                f"{DEFINITIONS_PATH}: options list '{options_name}' not found"
            )
            continue
        enum_map = _enum_map(enum_source, map_name, errors)
        if enum_map is None:
            continue
        map_values = {str(value).lower() for value in enum_map.values()}
        option_set = {str(option).lower() for option in options}
        if option_set != map_values:
            errors.append(
                f"{DEFINITIONS_PATH}: {options_name} {sorted(option_set)} does "
                f"not match the {map_name} value set {sorted(map_values)}"
            )
        for lang, path in TRANSLATION_PATHS.items():
            reference = references.get(("select", "hk{n}_betriebsart"), {}).get(lang)
            if select_key != "hk1_betriebsart":
                block = _state_block(
                    _load_json(path, errors) or {}, path, "select", select_key, errors
                )
            else:
                block = reference
            if block is None:
                continue
            if missing := sorted(option_set - set(block)):
                errors.append(
                    f"{path}: entity.select.{select_key}.state is missing "
                    f"translations for select options {missing}"
                )


def main() -> int:
    """Run all consistency checks and report drift."""
    errors: list[str] = []
    notes: list[str] = []

    translations: dict[str, dict[str, Any]] = {}
    for lang, path in TRANSLATION_PATHS.items():
        loaded = _load_json(path, errors)
        if loaded is not None:
            translations[lang] = loaded

    enum_source = _read_source(ENUM_MAPPINGS_PATH, errors)
    definitions_source = _read_source(DEFINITIONS_PATH, errors)

    if (
        len(translations) == len(TRANSLATION_PATHS)
        and enum_source
        and definitions_source
    ):
        references = check_family_copies(translations, errors)
        check_enum_coverage(references, enum_source, errors, notes)
        check_select_options(definitions_source, enum_source, references, errors)

    for note in notes:
        sys.stdout.write(f"TRANSLATION CONSISTENCY NOTE: {note}\n")
    if errors:
        for error in errors:
            sys.stderr.write(f"TRANSLATION CONSISTENCY ERROR: {error}\n")
        return 1
    sys.stdout.write("Translation consistency checks passed.\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
