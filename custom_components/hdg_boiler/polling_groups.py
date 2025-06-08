"""
Polling group definitions for the HDG Bavaria Boiler integration.

This file defines the structure of API polling groups, including the
nodes they contain, the API payload strings, and default scan intervals.
These definitions were moved from const.py to improve modularity.
"""

from __future__ import annotations

__version__ = "0.1.1"

from typing import Final

from .models import NodeGroupPayload

# Node lists for each polling group.
_GROUP1_NODES: Final[list[str]] = [  # Realtime Core Values (34 Nodes)
    "20000T",  # aussentemperatur
    "22000T",  # brennraumtemperatur_soll
    "22001T",  # kessel_abgastemperatur_ist
    "22002T",  # kessel_restsauerstoff_ist
    "22003T",  # kesseltemperatur_ist
    "22004T",  # kessel_rucklauftemperatur_ist
    "22005T",  # materialmenge_aktuell
    "22008T",  # primarluftklappe_ist
    "22009T",  # sekundarluftklappe_ist
    "22010T",  # kessel_status
    "22019T",  # primarluftklappe_soll
    "22021T",  # kessel_externe_anforderung
    "22022T",  # kesselvorlauf_solltemperatur
    "22023T",  # kesselrucklauf_solltemperatur
    "22024T",  # kesselleistung_ist
    "22030T",  # kessel_saugzuggeblase_ist
    "22031T",  # kessel_unterdruck_ist
    "22033T",  # sekundarluftklappe_soll
    "22043T",  # kessel_rucklaufmischer
    "22044T",  # abgasleitwert_ist
    "22045T",  # kessel_restsauerstoff_korr
    "22049T",  # abgasleitwert_soll
    "22050T",  # kessel_o2_sollwert
    "22052T",  # kessel_nachlegemenge
    "22057T",  # kessel_nachlegebedarf
    "22068T",  # stillstandszeit_soll
    "22070T",  # kessel_stillstandszeit
    "22098T",  # angeforderte_temperatur_abnehmer
    "24000T",  # puffer_temperatur_oben
    "24001T",  # puffer_temperatur_mitte
    "24002T",  # puffer_temperatur_unten
    "24023T",  # puffer_ladezustand
    "26000T",  # hk1_vorlauftemperatur_ist
    "26099T",  # hk1_vorlauftemperatur_soll
]

_GROUP2_NODES: Final[list[str]] = [  # General Status Values (7 Nodes)
    "22020T",  # kessel_haupt_betriebsart
    "22026T",  # kessel_betriebsphase_text
    "22029T",  # kessel_ausbrandgrund
    "24015T",  # puffer_status
    "26007T",  # hk1_mischer_status_text
    "26008T",  # hk1_pumpe_status_text
    "26011T",  # hk1_aktuelle_betriebsart
]

_GROUP3_NODES: Final[list[str]] = [  # Configuration & Counters Part 1 (32 Nodes)
    "1T",  # sprache
    "2T",  # bauart
    "3T",  # kesseltyp_kennung
    "4T",  # stromnetz
    "6T",  # brennstoff
    "9T",  # automatische_zeitumstellung
    "11T",  # einstiegsbild
    "13T",  # holzart
    "14T",  # holzfeuchte
    "15T",  # automatische_zundung_aktivieren
    "16T",  # auto_zundung_webcontrol_erlauben
    "17T",  # objektwarmebedarf
    "18T",  # minimale_nachlegemenge
    "19T",  # nachlegeschritt_text (also used by 'nachlegeschritt')
    "20T",  # nachlege_benachrichtigung
    "36T",  # offset_aussenfuhler
    "2113T",  # kesseltemperatur_sollwert_param
    "2114T",  # frostschutzprogramm_aktivieren
    "2115T",  # frostschutz_zirkulation_at_kleiner
    "2116T",  # frostschutz_rlt_kleiner
    "2117T",  # frostschutz_rlt_groesser
    "2123T",  # offset_kesseltemperatur_soll_maximum
    "2302T",  # anzunden_zeitdauer
    "2303T",  # anzunden_primarluft
    "2304T",  # anzunden_sekundarluft
    "2306T",  # anheizen_zeitdauer
    "2320T",  # auto_zundung_einschaltverzogerung
    "2402T",  # ausbrennen_primarluft
    "2403T",  # ausbrennen_sekundarluft
    "2407T",  # ausbrennen_bezugsgrosse
    "2603T",  # festwertvorgabe_primarluft
    "2604T",  # festwertvorgabe_sekundarluft
]

_GROUP4_NODES: Final[list[str]] = [  # Configuration & Counters Part 2 (40 Nodes)
    "2623T",  # pid3_o2_sekundarluft_minimum
    "2624T",  # pid3_o2_sekundarluft_maximum
    "2805T",  # rucklaufmischer_laufzeit_gesamt
    "2813T",  # pid_sollwert_rucklauf_spreizung_minimum
    "2816T",  # restwarmenutzung_puffer_bezug
    "2901T",  # freigabe_kesseltemperatur
    "2904T",  # freigabe_abgastemperatur
    "4020T",  # puffer_1_bezeichnung
    "4033T",  # puffer_1_ladung_abbruch_temperatur_oben
    "4036T",  # puffer_1_fuhler_quelle
    "4060T",  # puffer_1_energieberechnung_aktivieren
    "4061T",  # puffer_1_temperatur_kalt
    "4062T",  # puffer_1_temperatur_warm
    "4064T",  # puffer_1_nachlegemenge_optimieren
    "4065T",  # puffer_1_grosse
    "4070T",  # puffer_1_umladesystem_aktivieren
    "4090T",  # puffer_1_beladeventil_aktivieren
    "4091T",  # puffer_1_zonenventil_aktivieren
    "4095T",  # puffer_1_y2_ventil_aktivieren
    "4099T",  # puffer_art
    "6020T",  # heizkreis_1_system
    "6021T",  # hk1_bezeichnung
    "6022T",  # hk1_soll_normal
    "6023T",  # hk1_soll_absenk
    "6024T",  # hk1_parallelverschiebung
    "6025T",  # hk1_raumeinflussfaktor
    "6026T",  # hk1_steilheit
    "6027T",  # hk1_vorlauftemperatur_minimum
    "6028T",  # hk1_vorlauftemperatur_maximum
    "6029T",  # hk1_raumeinheit_status
    "6030T",  # hk1_offset_raumfuhler
    "6039T",  # hk1_warmequelle
    "6041T",  # hk1_mischerlaufzeit_maximum
    "6046T",  # hk1_pumpe_ein_freigabetemperatur
    "6047T",  # hk1_pumpe_aus_aussentemperatur
    "6048T",  # hk1_frostschutz_temp
    "6049T",  # hk1_eco_absenken_aus_aussentemperatur
    "6050T",  # heizgrenze_sommer
    "6051T",  # heizgrenze_winter
    "6067T",  # hk1_restwarme_aufnehmen
]

_GROUP5_NODES: Final[list[str]] = [  # Configuration & Counters Part 3 (41 Nodes)
    "20003T",  # software_version_touch
    "20026T",  # anlagenbezeichnung_sn
    "20031T",  # mac_adresse
    "20032T",  # anlage_betriebsart
    "20033T",  # anlage_status_text
    "20036T",  # software_version_fa
    "20037T",  # extra_version_info
    "20039T",  # hydraulikschema_nummer
    "22011T",  # kessel_betriebsstunden
    "22012T",  # laufzeit_wt_reinigung
    "22013T",  # laufzeit_entaschung
    "22014T",  # laufzeit_hauptgeblase
    "22015T",  # laufzeit_zundgeblase
    "22016T",  # anzahl_rostkippungen
    "22025T",  # kessel_restlaufzeit_wartung
    "22028T",  # kessel_wirkungsgrad
    "22037T",  # betriebsstunden_rostmotor
    "22038T",  # betriebsstunden_stokerschnecke
    "22039T",  # betriebsstunden_ascheschnecke
    "22040T",  # restlaufzeit_schornsteinfeger
    "22041T",  # kessel_typ_info_leer
    "22046T",  # primarluft_korrektur_o2
    "22053T",  # kessel_nachlegezeitpunkt_2
    "22054T",  # kessel_energieverbrauch_tag_gesamt
    "22062T",  # kessel_nachlegen_anzeige_text
    "22064T",  # zeit_kesseluberhitzung_10_abbrande_std
    "22065T",  # zeit_kesseluberhitzung_10_abbrande_prozent
    "22066T",  # zeit_kesseluberhitzung_gesamt_std
    "22067T",  # zeit_kesseluberhitzung_gesamt_prozent
    "22069T",  # kessel_warmemenge_gesamt
    "24004T",  # puffer_soll_oben
    "24006T",  # puffer_rucklauf_soll
    "24016T",  # puffer_energie_max
    "24017T",  # puffer_energie_aktuell
    "24019T",  # puffer_ladezustand_alt
    "24020T",  # puffer_energie_gesamt_zahler
    "24021T",  # puffer_energie_ist
    "24022T",  # puffer_energie_aufnehmbar
    "24098T",  # puffer_vorlauf_extern
    "24099T",  # puffer_rucklauf_extern
    "26004T",  # hk1_temp_quelle_status_wert
]


def _extract_node_base_for_payload(node_id: str) -> str:
    """Remove a single trailing 'T' if present, otherwise leave unchanged. Used for payload string generation."""
    return node_id.removesuffix("T")


# Defines the polling groups, their constituent nodes, and API payload strings.
HDG_NODE_PAYLOADS: Final[dict[str, NodeGroupPayload]] = {
    "group1_realtime_core": {
        "name": "Realtime Core",
        "nodes": _GROUP1_NODES,
        "payload_str": f"nodes={'T-'.join([_extract_node_base_for_payload(node) for node in _GROUP1_NODES])}T",
        # These string literals will be matched against constants defined in const.py
        "config_key_scan_interval": "scan_interval_realtime_core",
        "default_scan_interval": 15,  # Corresponds to DEFAULT_SCAN_INTERVAL_GROUP1
    },
    "group2_status_general": {
        "name": "General Status",
        "nodes": _GROUP2_NODES,
        "payload_str": f"nodes={'T-'.join([_extract_node_base_for_payload(node) for node in _GROUP2_NODES])}T",
        "config_key_scan_interval": "scan_interval_status_general",
        "default_scan_interval": 304,  # Corresponds to DEFAULT_SCAN_INTERVAL_GROUP2
    },
    "group3_config_counters_1": {
        "name": "Config/Counters 1",
        "nodes": _GROUP3_NODES,
        "payload_str": f"nodes={'T-'.join([_extract_node_base_for_payload(node) for node in _GROUP3_NODES])}T",
        "config_key_scan_interval": "scan_interval_config_counters_1",
        "default_scan_interval": 86410,  # Corresponds to DEFAULT_SCAN_INTERVAL_GROUP3
    },
    "group4_config_counters_2": {
        "name": "Config/Counters 2",
        "nodes": _GROUP4_NODES,
        "payload_str": f"nodes={'T-'.join([_extract_node_base_for_payload(node) for node in _GROUP4_NODES])}T",
        "config_key_scan_interval": "scan_interval_config_counters_2",
        "default_scan_interval": 86420,  # Corresponds to DEFAULT_SCAN_INTERVAL_GROUP4
    },
    "group5_config_counters_3": {
        "name": "Config/Counters 3",
        "nodes": _GROUP5_NODES,
        "payload_str": f"nodes={'T-'.join([_extract_node_base_for_payload(node) for node in _GROUP5_NODES])}T",
        "config_key_scan_interval": "scan_interval_config_counters_3",
        "default_scan_interval": 86430,  # Corresponds to DEFAULT_SCAN_INTERVAL_GROUP5
    },
}

# Defines the order in which polling groups are processed, especially during initial setup.
POLLING_GROUP_ORDER: Final[list[str]] = [
    "group1_realtime_core",
    "group2_status_general",
    "group3_config_counters_1",
    "group4_config_counters_2",
    "group5_config_counters_3",
]
