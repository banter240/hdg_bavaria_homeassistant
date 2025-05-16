"""
Constants for the HDG Bavaria Boiler integration.

This file defines shared constants, type definitions, and the core SENSOR_DEFINITIONS
which map HDG API nodes to Home Assistant entities.
"""

__version__ = "0.9.0"

from typing import Final, TypedDict, Optional, Dict, List

from homeassistant.components.sensor import SensorStateClass, SensorDeviceClass
from homeassistant.const import (
    PERCENTAGE,
    UnitOfEnergy,
    UnitOfPower,
    UnitOfPressure,
    UnitOfTemperature,
    UnitOfTime,
    UnitOfVolume,
)
from homeassistant.helpers.entity import EntityCategory

DOMAIN: Final = "hdg_boiler"

# Configuration defaults
DEFAULT_HOST_IP: Final = ""  # Default placeholder for host IP address
DEFAULT_NAME: Final = "HDG Boiler"  # Default name for the integration instance

# API Communication
API_ENDPOINT_DATA_REFRESH: Final = "/ApiManager.php?action=dataRefresh"
API_ENDPOINT_SET_VALUE: Final = "/ActionManager.php?action=set_value_changed"
API_TIMEOUT: Final = 30  # Default timeout for API requests in seconds

# Configuration keys from Config Flow / Options Flow
CONF_HOST_IP: Final = "host_ip"
CONF_DEVICE_ALIAS: Final = "device_alias"
CONF_SCAN_INTERVAL_GROUP1: Final = "scan_interval_realtime_core"
CONF_SCAN_INTERVAL_GROUP2: Final = "scan_interval_status_general"
CONF_SCAN_INTERVAL_GROUP3: Final = "scan_interval_config_counters_1"
CONF_SCAN_INTERVAL_GROUP4: Final = "scan_interval_config_counters_2"
CONF_SCAN_INTERVAL_GROUP5: Final = "scan_interval_config_counters_3"
CONF_ENABLE_DEBUG_LOGGING: Final = "enable_debug_logging"

# Default scan intervals for polling groups in seconds
# Group 1: Core real-time data, polled frequently.
DEFAULT_SCAN_INTERVAL_GROUP1: Final = 15  # 15 seconds

# Group 2: General status data.
# Polled approximately every 5 minutes (300s). The additional 11 seconds
# help to desynchronize polling cycles from Group 1 and other potential
# fixed-interval tasks, reducing the likelihood of simultaneous API requests.
DEFAULT_SCAN_INTERVAL_GROUP2: Final = 304  # Approx. 5 minutes (300s + 4s stagger)

# Groups 3-5: Configuration and less frequently changing counter data.
# Polled approximately daily (86400s = 24 hours).
# The small offsets (10s, 20s, 30s) serve to stagger these long-interval polls
# relative to each other and to the daily boundary, further distributing API load
# and preventing them from all triggering at the exact same moment after a restart
# or if aligned by chance.
DEFAULT_SCAN_INTERVAL_GROUP3: Final = 86410  # Approx. 24 hours (86400s + 10s stagger)
DEFAULT_SCAN_INTERVAL_GROUP4: Final = 86420  # Approx. 24 hours (86400s + 20s stagger)
DEFAULT_SCAN_INTERVAL_GROUP5: Final = 86430  # Approx. 24 hours (86400s + 30s stagger)

# Default setting for enabling detailed debug logging for polling cycles.
DEFAULT_ENABLE_DEBUG_LOGGING: Final = False

# Debounce delay for setting number values to prevent API flooding
NUMBER_SET_VALUE_DEBOUNCE_DELAY_S: Final = 2.0


class NodeGroupPayload(TypedDict):
    """Structure for defining an HDG API node polling group and its configuration."""

    name: str  # User-friendly name for the group (used in config flow descriptions)
    nodes: List[str]  # List of HDG node IDs (with suffix) belonging to this group
    payload_str: str  # The exact payload string for the API request (e.g., "nodes=ID1T-ID2T-ID3T")
    config_key_scan_interval: str  # Key used in config/options flow for this group's scan interval
    default_scan_interval: int  # Default scan interval in seconds for this group


# Define node lists for each group to ensure DRY principle for payload_str generation
# These lists contain the HDG node IDs (with their 'T' suffix where applicable)
# that belong to each polling group.
_GROUP1_NODES: Final[List[str]] = [  # Realtime Core Values (34 Nodes)
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

_GROUP2_NODES: Final[List[str]] = [  # General Status Values (7 Nodes)
    "22020T",  # kessel_haupt_betriebsart
    "22026T",  # kessel_betriebsphase_text
    "22029T",  # kessel_ausbrandgrund
    "24015T",  # puffer_status
    "26007T",  # hk1_mischer_status_text
    "26008T",  # hk1_pumpe_status_text
    "26011T",  # hk1_aktuelle_betriebsart
]

_GROUP3_NODES: Final[List[str]] = [  # Configuration & Counters Part 1 (32 Nodes)
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

_GROUP4_NODES: Final[List[str]] = [  # Configuration & Counters Part 2 (40 Nodes)
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

_GROUP5_NODES: Final[List[str]] = [  # Configuration & Counters Part 3 (41 Nodes)
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


# Defines the polling groups, their constituent nodes, and API payload strings.
HDG_NODE_PAYLOADS: Final[Dict[str, NodeGroupPayload]] = {
    "group1_realtime_core": {
        "name": "Realtime Core",
        "nodes": _GROUP1_NODES,
        "payload_str": f"nodes={'T-'.join([node.rstrip('T') for node in _GROUP1_NODES])}T",
        "config_key_scan_interval": CONF_SCAN_INTERVAL_GROUP1,
        "default_scan_interval": DEFAULT_SCAN_INTERVAL_GROUP1,
    },
    "group2_status_general": {
        "name": "General Status",
        "nodes": _GROUP2_NODES,
        "payload_str": f"nodes={'T-'.join([node.rstrip('T') for node in _GROUP2_NODES])}T",
        "config_key_scan_interval": CONF_SCAN_INTERVAL_GROUP2,
        "default_scan_interval": DEFAULT_SCAN_INTERVAL_GROUP2,
    },
    "group3_config_counters_1": {
        "name": "Config/Counters 1",
        "nodes": _GROUP3_NODES,
        "payload_str": f"nodes={'T-'.join([node.rstrip('T') for node in _GROUP3_NODES])}T",
        "config_key_scan_interval": CONF_SCAN_INTERVAL_GROUP3,
        "default_scan_interval": DEFAULT_SCAN_INTERVAL_GROUP3,
    },
    "group4_config_counters_2": {
        "name": "Config/Counters 2",
        "nodes": _GROUP4_NODES,
        "payload_str": f"nodes={'T-'.join([node.rstrip('T') for node in _GROUP4_NODES])}T",
        "config_key_scan_interval": CONF_SCAN_INTERVAL_GROUP4,
        "default_scan_interval": DEFAULT_SCAN_INTERVAL_GROUP4,
    },
    "group5_config_counters_3": {
        "name": "Config/Counters 3",
        "nodes": _GROUP5_NODES,
        "payload_str": f"nodes={'T-'.join([node.rstrip('T') for node in _GROUP5_NODES])}T",
        "config_key_scan_interval": CONF_SCAN_INTERVAL_GROUP5,
        "default_scan_interval": DEFAULT_SCAN_INTERVAL_GROUP5,
    },
}

# Defines the order in which polling groups are processed, especially during initial setup.
POLLING_GROUP_ORDER: Final[List[str]] = [
    "group1_realtime_core",
    "group2_status_general",
    "group3_config_counters_1",
    "group4_config_counters_2",
    "group5_config_counters_3",
]


class EnumOption(TypedDict):
    """Represents a single option in an enumeration, with translations."""

    de: str  # German translation
    en: str  # English translation


# Mappings for HDG API enumeration values to human-readable text (German and English).
# Used by sensors that represent enumerated states.
HDG_ENUM_MAPPINGS: Final[Dict[str, Dict[int, EnumOption]]] = {
    "SPRACHE": {
        0: {"de": "Deutsch", "en": "German"},
        1: {"de": "Englisch", "en": "English"},
        2: {"de": "Dänisch", "en": "Danish"},
        3: {"de": "Französisch", "en": "French"},
        4: {"de": "Spanisch", "en": "Spanish"},
        5: {"de": "Italienisch", "en": "Italian"},
        6: {"de": "Niederländisch", "en": "Dutch"},
        7: {"de": "Norwegisch", "en": "Norwegian"},
        8: {"de": "Schwedisch", "en": "Swedish"},
        9: {"de": "Polnisch", "en": "Polish"},
        10: {"de": "Slowenisch", "en": "Slovenian"},
        11: {"de": "Tschechisch", "en": "Czech"},
        12: {"de": "Ungarisch", "en": "Hungarian"},
        13: {"de": "Russisch", "en": "Russian"},
        14: {"de": "Finnisch", "en": "Finnish"},
        15: {"de": "Lettisch", "en": "Latvian"},
        16: {"de": "Litauisch", "en": "Lithuanian"},
        17: {"de": "Estnisch", "en": "Estonian"},
        18: {"de": "Rumänisch", "en": "Romanian"},
        19: {"de": "Bulgarisch", "en": "Bulgarian"},
        20: {"de": "Kroatisch", "en": "Croatian"},
        21: {"de": "Serbisch", "en": "Serbian"},
        22: {"de": "Griechisch", "en": "Greek"},
        23: {"de": "Portugiesisch", "en": "Portuguese"},
    },
    "ON_OFF_RSI": {0: {"de": "Aus", "en": "Off"}, 1: {"de": "Ein", "en": "On"}},
    "YES_NO_RSI": {0: {"de": "Nein", "en": "No"}, 1: {"de": "Ja", "en": "Yes"}},
    "ON/OFF": {0: {"de": "Aus", "en": "Off"}, 1: {"de": "Ein", "en": "On"}},
    "YES/NO": {0: {"de": "Nein", "en": "No"}, 1: {"de": "Ja", "en": "Yes"}},
    "KESSELSTATUS": {
        0: {"de": "Störung", "en": "Fault"},
        1: {"de": "Bereit", "en": "Ready"},
        2: {"de": "Reinigung", "en": "Cleaning"},
        3: {"de": "Vorbelüften", "en": "Pre-ventilation"},
        4: {"de": "Füllen", "en": "Filling"},
        5: {"de": "Anzünden", "en": "Ignition"},
        6: {"de": "Anzünden kühlen", "en": "Cooling ignition"},
        7: {"de": "Anheizen", "en": "Heating-up"},
        8: {"de": "Automatik", "en": "Automatic"},
        9: {"de": "Ausbrennen", "en": "Burn out"},
        10: {"de": "Gluterhaltung", "en": "Keep embers glow"},
        11: {"de": "Lambdatest", "en": "Lambda test"},
        12: {"de": "Schutzprogramm", "en": "Protection program"},
        13: {"de": "Ausgeschaltet", "en": "Turned off"},
        14: {"de": "Zündung bereit", "en": "Ignition ready"},
        15: {"de": "Unbekannt 15", "en": "Unknown 15"},  # Placeholder if value observed
        16: {"de": "Ausbrennen (SHK)", "en": "Burn out (SHK)"},
        17: {"de": "Abgastemp.–Stopp", "en": "Fluegas temp.stop"},
        18: {"de": "Restwärmenutzung", "en": "Resid.heat utilis."},
    },
    "AUSBRANDGRUND": {
        0: {"de": " ", "en": " "},  # API can return empty string for this
        1: {"de": "Rostkippung", "en": "Tip grate"},
        2: {"de": "Keine Anforderung", "en": "No demand"},
        3: {"de": "Abschaltung", "en": "Switch-off"},
    },
    "PUFFER_ZUSTAND": {
        0: {"de": "Aus", "en": "Off"},
        1: {"de": "Absenken", "en": "Lowering"},
        2: {"de": "Normal", "en": "Normal"},
        3: {"de": "Zwangsladung", "en": "Forced Charge"},
    },
    "AUS/AUF/ZU/STOERUNG": {
        0: {"de": "Aus", "en": "Off"},
        1: {"de": "Auf", "en": "Open"},
        2: {"de": "Zu", "en": "Closed"},
        3: {"de": "Störung", "en": "Fault"},
    },
    "OFF/ON/STOERUNG": {
        0: {"de": "Aus", "en": "Off"},
        1: {"de": "Ein", "en": "On"},
        2: {"de": "Störung", "en": "Fault"},
    },
    "HEIZKREIS_CURRENT": {
        0: {"de": "Abgesenkt", "en": "Reduced"},
        1: {"de": "Aus", "en": "Off"},
        2: {"de": "Standard", "en": "Standard"},
        3: {"de": "Tagbetrieb", "en": "Day mode"},
        4: {"de": "Nachtbetrieb", "en": "Night mode"},
        5: {"de": "Partybetrieb", "en": "Party mode"},
        6: {"de": "Urlaubsbetrieb", "en": "Holiday mode"},
        7: {"de": "Sommerbetrieb", "en": "Summer mode"},
    },
    "KESSEL_HBA": {  # Kessel Haupt-Betriebsart
        0: {"de": "Ausgeschaltet", "en": "Turned off"},
        1: {"de": "Abschaltvorgang", "en": "Power down"},
        2: {"de": "Eingeschaltet", "en": "Turned on"},
        3: {"de": "Festwert", "en": "Fixed value"},
        4: {"de": "Schornsteinfeger", "en": "Chimney sweep"},
        5: {"de": "Aktoren Anlage", "en": "Actuator system"},
        6: {"de": "Aktoren Zuführung", "en": "Actuator feed"},
        7: {"de": "Autobinding", "en": "Autobinding"},
        8: {"de": "Unbekannt", "en": "Unknown"},  # Fallback
    },
    "HK_BETRIEBSPHASE": {  # Heizkreis Betriebsphase (likely for pellet burners, not wood log)
        0: {"de": "Störabschaltung", "en": "Fault shutdown"},
        1: {"de": "Brenner gesperrt", "en": "Burner disabled"},
        2: {"de": "WE einschalten", "en": "Turn on WE"},  # WE = Wärmeerzeuger (Heat generator)
        3: {"de": "Selbsttest", "en": "Self test"},
        4: {"de": "WE ausschalten", "en": "Turn off WE"},
        5: {"de": "Standby", "en": "Standby"},
        6: {"de": "Brenner aus", "en": "Burner off"},
        7: {"de": "Vorspülen", "en": "Flushing"},
        8: {"de": "Zündphase", "en": "Ignition phase"},
        9: {"de": "Flammenstabilisierung", "en": "Flame stabilisation"},
        10: {"de": "Modulationsbetrieb", "en": "Modulation phase"},
        11: {"de": "Modulation Fixleistung", "en": "Fix output modulation"},
        12: {"de": "Modulation Entaschung", "en": "De-ashing modulation"},
        13: {"de": "Ausbrand", "en": "Burn-out"},
        14: {"de": " ", "en": " "},  # API can return empty string
    },
    "NACHLEGEZEITPUNKT_BENACHRICHTIGUNG": {
        0: {"de": "Niemals", "en": "Never"},
        1: {"de": "bei Änderung um 30 min", "en": "if changed by 30 min"},
        2: {"de": "bei Änderung um 1 h", "en": "if changed by 1 h"},
        3: {"de": "bei Änderung um > 2 h", "en": "if changed by > 2 h"},
    },
    "HK_SYSTEM": {  # Heizkreis Systemart
        0: {"de": "Keines", "en": "None"},
        1: {"de": "Heizkörper", "en": "Radiators"},
        2: {"de": "Fußboden", "en": "Underfloor heat"},
        3: {"de": "Konstant", "en": "Constant"},
        4: {"de": "Ungeregelt", "en": "Uncontrolled"},
    },
    "BAUART": {  # Boiler type
        0: {"de": "SAL", "en": "SAL"},  # Scheitholz (Log wood)
        1: {"de": "HSF", "en": "HSF"},  # Hackschnitzel (Wood chips)
        2: {"de": "PHA", "en": "PHA"},  # Pellets
        3: {"de": "SHK", "en": "SHK"},  # Scheitholz-Kombi (Log wood combi)
    },
    "KESSELTYP": {  # Specific boiler model identifier
        0: {"de": "Slave", "en": "Slave"},
        1: {"de": "Master", "en": "Master"},
        2: {"de": "Compact 25", "en": "Compact 25"},
        3: {"de": "Compact 35", "en": "Compact 35"},
        4: {"de": "Compact 50", "en": "Compact 50"},
        5: {"de": "Compact 65", "en": "Compact 65"},
        6: {"de": "Compact 80", "en": "Compact 80"},
        7: {"de": "K10", "en": "K10"},
        8: {"de": "K15", "en": "K15"},
        9: {"de": "K21", "en": "K21"},
        10: {"de": "K26", "en": "K26"},
        11: {"de": "K35", "en": "K35"},
        12: {"de": "K45", "en": "K45"},
        13: {"de": "K60", "en": "K60"},
        14: {"de": "F20", "en": "F20"},
        15: {"de": "F25", "en": "F25"},
        16: {"de": "F30", "en": "F30"},
        17: {"de": "F40", "en": "F40"},
        18: {"de": "F50", "en": "F50"},
        19: {"de": "Euro 30", "en": "Euro 30"},
        20: {"de": "Euro 40", "en": "Euro 40"},
        21: {"de": "Euro 50", "en": "Euro 50"},
        22: {"de": "H20", "en": "H20"},
        23: {"de": "H25", "en": "H25"},
        24: {"de": "H30", "en": "H30"},
        25: {"de": "FK Hybrid 20/15", "en": "FK Hybrid 20/15"},
        26: {"de": "FK Hybrid 30/15", "en": "FK Hybrid 30/15"},
        27: {"de": "FK Hybrid 30/26", "en": "FK Hybrid 30/26"},
        28: {"de": "FK Hybrid 40/26", "en": "FK Hybrid 40/26"},
        29: {"de": "FK Hybrid 50/26", "en": "FK Hybrid 50/26"},
        30: {"de": "K33", "en": "K33"},
        31: {"de": "Compact 40", "en": "Compact 40"},
        32: {"de": "Compact 95", "en": "Compact 95"},
        33: {"de": "Compact 30", "en": "Compact 30"},
        34: {"de": "K38", "en": "K38"},
        35: {"de": "K45 (2)", "en": "K45 (2)"},  # Assuming this is a distinct model
        36: {"de": "K50", "en": "K50"},
        37: {"de": "K63", "en": "K63"},
        # Add more known KESSELTYP values here if available
    },
    "STROMNETZ": {  # Power grid type
        0: {"de": "3x400V", "en": "3x400V"},
        1: {"de": "3x230V", "en": "3x230V"},
        2: {"de": "1x230V", "en": "1x230V"},
    },
    "BRENNSTOFF": {  # Fuel type selection
        0: {"de": "Material 1", "en": "Fuel 1"},
        1: {"de": "Material 2", "en": "Fuel 2"},
        2: {"de": "Material 3", "en": "Fuel 3"},
        3: {"de": "Material 4", "en": "Fuel 4"},
    },
    "EINSTIEGSBILD": {  # Default screen on boiler display
        0: {"de": "Heizkessel", "en": "Boiler"},
        1: {"de": "Puffer 1", "en": "Accumulator 1"},
        2: {"de": "Puffer 2", "en": "Accumulator 2"},
        3: {"de": "Ext. Wärmequelle", "en": "Ext. Heat Source"},
        4: {"de": "Heizkreis 1", "en": "Heating Circuit 1"},
        5: {"de": "Heizkreis 2", "en": "Heating Circuit 2"},
        6: {"de": "Heizkreis 3", "en": "Heating Circuit 3"},
        7: {"de": "Heizkreis 4", "en": "Heating Circuit 4"},
        8: {"de": "Heizkreis 5", "en": "Heating Circuit 5"},
        9: {"de": "Heizkreis 6", "en": "Heating Circuit 6"},
        10: {"de": "Netzpumpe 1", "en": "Network Pump 1"},
        11: {
            "de": "Netzpumpe 2",
            "en": "Network Pump 2",
        },  # Assuming 11 is Netzpumpe 2 based on pattern
        12: {"de": "Netzpumpe 3", "en": "Network Pump 3"},  # Assuming 12 is Netzpumpe 3
        13: {"de": "Brauchwasser 1", "en": "Domestic Hot Water 1"},  # Assuming 13 based on pattern
        14: {"de": "Brauchwasser 1", "en": "Domestic Hot Water 1"},  # Original had 14
        15: {"de": "Brauchwasser 2", "en": "Domestic Hot Water 2"},
        16: {"de": "Solar", "en": "Solar"},
        17: {"de": "Austragung", "en": "Discharge System"},  # Assuming 17 based on pattern
        18: {"de": "Austragung", "en": "Discharge System"},  # Original had 18
    },
    "HOLZART": {  # Wood type for log boilers
        0: {"de": "Hartholz", "en": "Hardwood"},
        1: {"de": "Mischholz", "en": "Mixed wood"},
        2: {"de": "Weichholz", "en": "Softwood"},
        3: {"de": "Sägereste", "en": "Sawing waste"},
        4: {"de": "Holzbriketts", "en": "Wood briquettes"},
    },
    "HOLZFEUCHTE": {  # Wood moisture content
        0: {"de": "trockene Qualität", "en": "dry quality"},
        1: {"de": "mittlere Qualität", "en": "medium quality"},
        2: {"de": "feuchte Qualität", "en": "wet quality"},
    },
    "NACHLEGESCHRITT": {  # Step size for refueling amount
        0: {"de": "1%-Schritte", "en": "1%-steps"},
        1: {"de": "5%-Schritte", "en": "5%-steps"},
        2: {"de": "10%-Schritte", "en": "10%-steps"},
    },
    "ANLAGE_BETRIEBSART": {  # Overall system operating mode
        0: {"de": "Normal", "en": "Normal"},
        1: {"de": "Urlaubsbetrieb", "en": "Holiday mode"},
        2: {"de": "Sommerbetrieb", "en": "Summer mode"},
        3: {"de": "Frostschutz", "en": "Frost protection"},
    },
    "BETRIEBSART_CURRENT": {  # Current operating mode (often mirrors ANLAGE_BETRIEBSART)
        0: {"de": "Aus", "en": "Off"},
        1: {"de": "Ein", "en": "On"},
        2: {"de": "Urlaubsbetrieb", "en": "Holiday mode"},
        3: {"de": "Sommerbetrieb", "en": "Summer mode"},
        4: {"de": "Frostschutz", "en": "Frost protection"},
    },
    "RAUMEINHEIT": {  # Type of room control unit
        0: {"de": "Keine", "en": "None"},
        1: {"de": "Raumtemperaturfühler", "en": "Indoor thermostat unit"},
        2: {"de": "Raumbediengerät BUS", "en": "Room control unit BUS"},
        3: {"de": "Raumbediengerät LIGHT", "en": "Room control unit LIGHT"},
        4: {"de": "Raumbediengerät BUS NLM", "en": "Room control unit BUS(NLM)"},
        5: {"de": "Raumtemperaturfühler 2", "en": "Indoor thermostat unit 2"},  # Example additional
    },
    "QUELLE": {  # Heat source for a heating circuit
        0: {"de": "Keine", "en": "None"},
        1: {"de": "Kessel", "en": "Boiler"},
        2: {"de": "Puffer 1", "en": "Accumulator 1"},
        3: {"de": "Puffer 2", "en": "Accumulator 2"},
        4: {"de": "Netzpumpe 1", "en": "Network pump 1"},
        5: {"de": "Netzpumpe 2", "en": "Network pump 2"},
        6: {"de": "Netzpumpe 3", "en": "Network pump 3"},
        7: {"de": "Verband", "en": "Master"},  # (Master in a cascade system)
        8: {"de": "Solar", "en": "Solar"},  # Example additional
    },
    "PUFFER_ART": {  # Type of buffer/accumulator tank
        0: {"de": "Kein", "en": "None"},
        1: {"de": "Normal", "en": "Normal"},
        2: {"de": "Kombi", "en": "Combi"},
    },
    "HK_ESTRICHSCHRITT": {  # Screed drying program step for underfloor heating
        0: {"de": "Aus", "en": "Off"},
        1: {"de": "An - Anstieg", "en": "At - increase"},
        2: {"de": "An - Halten", "en": "At - hold"},
        3: {"de": "An - Abkühlen", "en": "At-cool down"},
    },
    "PUFFER_POS": {  # Sensor position in buffer tank
        0: {"de": "Puffer oben", "en": "Accumulator top"},
        1: {"de": "Puffer unten", "en": "Accumulator bottom"},
        2: {"de": "Puffer mitte", "en": "Accumulator middle"},
        3: {"de": "Puffer mitte-oben", "en": "Accumulator middle upper"},
        4: {"de": "Puffer mitte-unten", "en": "Accumulator middle lower"},
        5: {"de": "Puffer Rücklauf", "en": "Accumulator Return"},  # Example additional
    },
    "NACHLEGEN_ANZEIGE": {  # Refueling indicator status
        0: {"de": "nicht möglich", "en": "not possible"},
        1: {"de": "erlaubt, aber Stillstandszeit", "en": "allowed, but idle time"},
        2: {"de": "möglich und sinnvoll", "en": "possible and useful"},
        3: {"de": "notwendig, oder es wird kalt", "en": "necessary, or it gets cold"},
    },
    "KESSELAUSBRENNBEZUG": {  # Reference for boiler burnout, values might be specific
        0: {"de": "Standard", "en": "Standard"},  # Example, actual values might differ
        1: {"de": "Restsauerstoff", "en": "Residual Oxygen"},
        2: {"de": "Abgastemperatur", "en": "Flue Gas Temperature"},
    },
}


class SensorDefinition(TypedDict, total=False):
    """
    Defines the properties and HA platform configuration for a sensor or entity
    derived from an HDG boiler data node.
    """

    hdg_node_id: str  # The raw HDG API node ID, may include T/U/V/W/X/Y suffix for setters
    translation_key: str  # Key used for Home Assistant entity naming and unique ID suffix
    hdg_data_type: Optional[
        str
    ]  # Original data type from HDG API (e.g., "2" for numeric, "10" for enum)
    hdg_formatter: Optional[str]  # Formatter hint from HDG API (e.g., "iTEMP", "iPERC")
    hdg_enum_type: Optional[str]  # If it's an enum, key to HDG_ENUM_MAPPINGS
    ha_platform: str  # Target Home Assistant platform (e.g., "sensor", "number", "select")
    ha_device_class: Optional[
        str
    ]  # Home Assistant device class (e.g., SensorDeviceClass.TEMPERATURE)
    ha_native_unit_of_measurement: Optional[str]  # Native unit for HA entity
    ha_state_class: Optional[str]  # Home Assistant state class (e.g., SensorStateClass.MEASUREMENT)
    icon: Optional[str]  # Suggested mdi icon for the entity
    entity_category: Optional[EntityCategory]  # HA entity category (e.g., CONFIG, DIAGNOSTIC)
    writable: bool  # True if this node's value can be set via the API
    parse_as_type: Optional[
        str
    ]  # Hint for how to parse the raw text value from API (e.g., "float", "enum_text")
    # Fields for settable 'number' entities
    setter_type: Optional[str]  # Expected data type for API set validation (e.g., "int", "float1")
    setter_min_val: Optional[float]  # Minimum allowed value for setting
    setter_max_val: Optional[float]  # Maximum allowed value for setting
    setter_step: Optional[float]  # Step for numeric value adjustments when setting


# Master dictionary defining all sensors and entities for the integration.
# Each key is a unique identifier (often matching the translation_key) for the entity.
SENSOR_DEFINITIONS: Final[Dict[str, SensorDefinition]] = {
    "sprache": {
        "hdg_node_id": "1T",
        "translation_key": "sprache",
        "hdg_data_type": "10",
        "hdg_formatter": None,
        "hdg_enum_type": "SPRACHE",
        "ha_platform": "sensor",
        "icon": "mdi:translate",
        "writable": False,
        "parse_as_type": "enum_text",
    },
    "bauart": {
        "hdg_node_id": "2T",
        "translation_key": "bauart",
        "hdg_data_type": "10",
        "hdg_formatter": None,
        "hdg_enum_type": "BAUART",
        "ha_platform": "sensor",
        "icon": "mdi:tools",
        "writable": False,
        "parse_as_type": "enum_text",
        "entity_category": EntityCategory.DIAGNOSTIC,
    },
    "kesseltyp_kennung": {
        "hdg_node_id": "3T",
        "translation_key": "kesseltyp_kennung",
        "hdg_data_type": "10",
        "hdg_formatter": None,
        "hdg_enum_type": "KESSELTYP",
        "ha_platform": "sensor",
        "icon": "mdi:tag-text-outline",
        "writable": False,
        "parse_as_type": "enum_text",
        "entity_category": EntityCategory.DIAGNOSTIC,
    },
    "stromnetz": {
        "hdg_node_id": "4T",
        "translation_key": "stromnetz",
        "hdg_data_type": "10",
        "hdg_formatter": None,
        "hdg_enum_type": "STROMNETZ",
        "ha_platform": "sensor",
        "icon": "mdi:power-plug-outline",
        "writable": False,
        "parse_as_type": "enum_text",
    },
    "brennstoff": {
        "hdg_node_id": "6T",
        "translation_key": "brennstoff",
        "hdg_data_type": "10",
        "hdg_formatter": None,
        "hdg_enum_type": "BRENNSTOFF",
        "ha_platform": "sensor",
        "icon": "mdi:pine-tree-fire",
        "writable": False,
        "parse_as_type": "enum_text",
    },
    "automatische_zeitumstellung": {
        "hdg_node_id": "9T",
        "translation_key": "automatische_zeitumstellung",
        "hdg_data_type": "10",
        "hdg_formatter": None,
        "hdg_enum_type": "ON/OFF",
        "ha_platform": "sensor",
        "icon": "mdi:clock-time-eleven-outline",
        "writable": False,
        "parse_as_type": "enum_text",
    },
    "einstiegsbild": {
        "hdg_node_id": "11T",
        "translation_key": "einstiegsbild",
        "hdg_data_type": "10",
        "hdg_formatter": None,
        "hdg_enum_type": "EINSTIEGSBILD",
        "ha_platform": "sensor",
        "icon": "mdi:television-guide",
        "writable": False,
        "parse_as_type": "enum_text",
    },
    "holzart": {
        "hdg_node_id": "13T",
        "translation_key": "holzart",
        "hdg_data_type": "10",
        "hdg_formatter": None,
        "hdg_enum_type": "HOLZART",
        "ha_platform": "sensor",
        "icon": "mdi:tree-outline",
        "writable": False,
        "parse_as_type": "enum_text",
    },
    "holzfeuchte": {
        "hdg_node_id": "14T",
        "translation_key": "holzfeuchte",
        "hdg_data_type": "10",
        "hdg_formatter": None,
        "hdg_enum_type": "HOLZFEUCHTE",
        "ha_platform": "sensor",
        "icon": "mdi:water-percent",
        "writable": False,
        "parse_as_type": "enum_text",
    },
    "automatische_zundung_aktivieren": {
        "hdg_node_id": "15T",
        "translation_key": "automatische_zundung_aktivieren",
        "hdg_data_type": "10",
        "hdg_formatter": None,
        "hdg_enum_type": "YES/NO",
        "ha_platform": "sensor",
        "icon": "mdi:auto-fix",
        "writable": False,
        "parse_as_type": "enum_text",
    },
    "auto_zundung_webcontrol_erlauben": {
        "hdg_node_id": "16T",
        "translation_key": "auto_zundung_webcontrol_erlauben",
        "hdg_data_type": "10",
        "hdg_formatter": None,
        "hdg_enum_type": "YES/NO",
        "ha_platform": "sensor",
        "icon": "mdi:web-check",
        "writable": False,
        "parse_as_type": "enum_text",
        "entity_category": EntityCategory.DIAGNOSTIC,
    },
    "objektwarmebedarf": {
        "hdg_node_id": "17T",
        "translation_key": "objektwarmebedarf",
        "hdg_data_type": "2",
        "hdg_formatter": "iKW",
        "ha_platform": "sensor",
        "ha_device_class": SensorDeviceClass.POWER,
        "ha_native_unit_of_measurement": UnitOfPower.KILO_WATT,
        "ha_state_class": SensorStateClass.MEASUREMENT,
        "icon": "mdi:radiator",
        "writable": False,
        "parse_as_type": "float",
    },
    "minimale_nachlegemenge": {
        "hdg_node_id": "18T",
        "translation_key": "minimale_nachlegemenge",
        "hdg_data_type": "2",
        "hdg_formatter": "iPERC",
        "ha_platform": "sensor",
        "ha_native_unit_of_measurement": PERCENTAGE,
        "ha_state_class": SensorStateClass.MEASUREMENT,
        "icon": "mdi:basket-minus-outline",
        "writable": False,
        "parse_as_type": "float",
        "entity_category": EntityCategory.DIAGNOSTIC,
    },
    "nachlegeschritt_text": {
        "hdg_node_id": "19T",
        "translation_key": "nachlegeschritt_text",
        "hdg_data_type": "10",
        "hdg_formatter": None,
        "hdg_enum_type": "NACHLEGESCHRITT",
        "ha_platform": "sensor",
        "icon": "mdi:stairs-up",
        "writable": False,
        "parse_as_type": "enum_text",
    },
    "nachlegeschritt": {  # Duplicate hdg_node_id "19T" with different translation_key
        "hdg_node_id": "19T",
        "translation_key": "nachlegeschritt",
        "hdg_data_type": "10",
        "hdg_formatter": None,
        "hdg_enum_type": "NACHLEGESCHRITT",
        "ha_platform": "sensor",
        "ha_native_unit_of_measurement": PERCENTAGE,
        "ha_state_class": SensorStateClass.MEASUREMENT,
        "icon": "mdi:stairs",
        "writable": False,
        "parse_as_type": "percent_from_string_regex",
    },
    "nachlege_benachrichtigung": {
        "hdg_node_id": "20T",
        "translation_key": "nachlege_benachrichtigung",
        "hdg_data_type": "10",
        "hdg_formatter": None,
        "hdg_enum_type": "NACHLEGEZEITPUNKT_BENACHRICHTIGUNG",
        "ha_platform": "sensor",
        "icon": "mdi:basket-clock",
        "writable": False,
        "parse_as_type": "enum_text",
    },
    "offset_aussenfuhler": {
        "hdg_node_id": "36T",
        "translation_key": "offset_aussenfuhler",
        "hdg_data_type": "2",
        "hdg_formatter": "iTEMP",
        "ha_platform": "sensor",
        "ha_device_class": SensorDeviceClass.TEMPERATURE,
        "ha_native_unit_of_measurement": UnitOfTemperature.CELSIUS,
        "ha_state_class": SensorStateClass.MEASUREMENT,
        "icon": "mdi:thermometer-offset",
        "writable": False,
        "parse_as_type": "float",
        "entity_category": EntityCategory.DIAGNOSTIC,
    },
    "kesseltemperatur_sollwert_param": {
        "hdg_node_id": "2113T",
        "translation_key": "kesseltemperatur_sollwert_param",
        "hdg_data_type": "2",
        "hdg_formatter": "iTEMP",
        "ha_platform": "sensor",
        "ha_device_class": SensorDeviceClass.TEMPERATURE,
        "ha_native_unit_of_measurement": UnitOfTemperature.CELSIUS,
        "ha_state_class": SensorStateClass.MEASUREMENT,
        "icon": "mdi:thermometer-lines",
        "writable": False,
        "parse_as_type": "float",
    },
    "frostschutzprogramm_aktivieren": {
        "hdg_node_id": "2114T",
        "translation_key": "frostschutzprogramm_aktivieren",
        "hdg_data_type": "10",
        "hdg_formatter": None,
        "hdg_enum_type": "YES/NO",
        "ha_platform": "sensor",
        "icon": "mdi:snowflake-thermometer",
        "writable": False,
        "parse_as_type": "enum_text",
    },
    "frostschutz_zirkulation_at_kleiner": {
        "hdg_node_id": "2115T",
        "translation_key": "frostschutz_zirkulation_at_kleiner",
        "hdg_data_type": "2",
        "hdg_formatter": "iTEMP",
        "ha_platform": "sensor",
        "ha_device_class": SensorDeviceClass.TEMPERATURE,
        "ha_native_unit_of_measurement": UnitOfTemperature.CELSIUS,
        "ha_state_class": SensorStateClass.MEASUREMENT,
        "icon": "mdi:snowflake-alert",
        "writable": False,
        "parse_as_type": "float",
    },
    "frostschutz_rlt_kleiner": {
        "hdg_node_id": "2116T",
        "translation_key": "frostschutz_rlt_kleiner",
        "hdg_data_type": "2",
        "hdg_formatter": "iTEMP",
        "ha_platform": "sensor",
        "ha_device_class": SensorDeviceClass.TEMPERATURE,
        "ha_native_unit_of_measurement": UnitOfTemperature.CELSIUS,
        "ha_state_class": SensorStateClass.MEASUREMENT,
        "icon": "mdi:snowflake-alert",
        "writable": False,
        "parse_as_type": "float",
    },
    "frostschutz_rlt_groesser": {
        "hdg_node_id": "2117T",
        "translation_key": "frostschutz_rlt_groesser",
        "hdg_data_type": "2",
        "hdg_formatter": "iTEMP",
        "ha_platform": "sensor",
        "ha_device_class": SensorDeviceClass.TEMPERATURE,
        "ha_native_unit_of_measurement": UnitOfTemperature.CELSIUS,
        "ha_state_class": SensorStateClass.MEASUREMENT,
        "icon": "mdi:snowflake-check",
        "writable": False,
        "parse_as_type": "float",
    },
    "offset_kesseltemperatur_soll_maximum": {
        "hdg_node_id": "2123T",
        "translation_key": "offset_kesseltemperatur_soll_maximum",
        "hdg_data_type": "2",
        "hdg_formatter": "iKELV",
        "ha_platform": "sensor",
        "ha_native_unit_of_measurement": UnitOfTemperature.KELVIN,
        "ha_state_class": SensorStateClass.MEASUREMENT,
        "icon": "mdi:thermometer-plus",
        "writable": False,
        "parse_as_type": "float",
    },
    "anzunden_zeitdauer": {
        "hdg_node_id": "2302T",
        "translation_key": "anzunden_zeitdauer",
        "hdg_data_type": "2",
        "hdg_formatter": "iMIN",
        "ha_platform": "sensor",
        "ha_device_class": SensorDeviceClass.DURATION,
        "ha_native_unit_of_measurement": UnitOfTime.MINUTES,
        "ha_state_class": SensorStateClass.MEASUREMENT,
        "icon": "mdi:timer-fire",
        "writable": False,
        "parse_as_type": "float",
    },
    "anzunden_primarluft": {
        "hdg_node_id": "2303T",
        "translation_key": "anzunden_primarluft",
        "hdg_data_type": "2",
        "hdg_formatter": "iPERC",
        "ha_platform": "sensor",
        "ha_native_unit_of_measurement": PERCENTAGE,
        "ha_state_class": SensorStateClass.MEASUREMENT,
        "icon": "mdi:weather-windy",
        "writable": False,
        "parse_as_type": "float",
    },
    "anzunden_sekundarluft": {
        "hdg_node_id": "2304T",
        "translation_key": "anzunden_sekundarluft",
        "hdg_data_type": "2",
        "hdg_formatter": "iPERC",
        "ha_platform": "sensor",
        "ha_native_unit_of_measurement": PERCENTAGE,
        "ha_state_class": SensorStateClass.MEASUREMENT,
        "icon": "mdi:weather-windy-variant",
        "writable": False,
        "parse_as_type": "float",
    },
    "anheizen_zeitdauer": {
        "hdg_node_id": "2306T",
        "translation_key": "anheizen_zeitdauer",
        "hdg_data_type": "2",
        "hdg_formatter": "iMIN",
        "ha_platform": "sensor",
        "ha_device_class": SensorDeviceClass.DURATION,
        "ha_native_unit_of_measurement": UnitOfTime.MINUTES,
        "ha_state_class": SensorStateClass.MEASUREMENT,
        "icon": "mdi:fire-clock",
        "writable": False,
        "parse_as_type": "float",
    },
    "auto_zundung_einschaltverzogerung": {
        "hdg_node_id": "2320T",
        "translation_key": "auto_zundung_einschaltverzogerung",
        "hdg_data_type": "2",
        "hdg_formatter": "iMIN",
        "ha_platform": "sensor",
        "ha_device_class": SensorDeviceClass.DURATION,
        "ha_native_unit_of_measurement": UnitOfTime.MINUTES,
        "ha_state_class": SensorStateClass.MEASUREMENT,
        "icon": "mdi:timer-cog-outline",
        "writable": False,
        "parse_as_type": "float",
    },
    "ausbrennen_primarluft": {
        "hdg_node_id": "2402T",
        "translation_key": "ausbrennen_primarluft",
        "hdg_data_type": "2",
        "hdg_formatter": "iPERC",
        "ha_platform": "sensor",
        "ha_native_unit_of_measurement": PERCENTAGE,
        "ha_state_class": SensorStateClass.MEASUREMENT,
        "icon": "mdi:air-filter",
        "writable": False,
        "parse_as_type": "float",
    },
    "ausbrennen_sekundarluft": {
        "hdg_node_id": "2403T",
        "translation_key": "ausbrennen_sekundarluft",
        "hdg_data_type": "2",
        "hdg_formatter": "iPERC",
        "ha_platform": "sensor",
        "ha_native_unit_of_measurement": PERCENTAGE,
        "ha_state_class": SensorStateClass.MEASUREMENT,
        "icon": "mdi:air-filter",
        "writable": False,
        "parse_as_type": "float",
    },
    "ausbrennen_bezugsgrosse": {
        "hdg_node_id": "2407T",
        "translation_key": "ausbrennen_bezugsgrosse",
        "hdg_data_type": "10",
        "hdg_formatter": None,
        "hdg_enum_type": "KESSELAUSBRENNBEZUG",
        "ha_platform": "sensor",
        "icon": "mdi:axis-arrow",
        "writable": False,
        "parse_as_type": "enum_text",
    },
    "festwertvorgabe_primarluft": {
        "hdg_node_id": "2603T",
        "translation_key": "festwertvorgabe_primarluft",
        "hdg_data_type": "2",
        "hdg_formatter": "iPERC",
        "ha_platform": "sensor",
        "ha_native_unit_of_measurement": PERCENTAGE,
        "ha_state_class": SensorStateClass.MEASUREMENT,
        "icon": "mdi:tune-variant",
        "writable": False,
        "parse_as_type": "float",
    },
    "festwertvorgabe_sekundarluft": {
        "hdg_node_id": "2604T",
        "translation_key": "festwertvorgabe_sekundarluft",
        "hdg_data_type": "2",
        "hdg_formatter": "iPERC",
        "ha_platform": "sensor",
        "ha_native_unit_of_measurement": PERCENTAGE,
        "ha_state_class": SensorStateClass.MEASUREMENT,
        "icon": "mdi:tune-variant",
        "writable": False,
        "parse_as_type": "float",
    },
    "pid3_o2_sekundarluft_minimum": {
        "hdg_node_id": "2623T",
        "translation_key": "pid3_o2_sekundarluft_minimum",
        "hdg_data_type": "2",
        "hdg_formatter": "iPERC",
        "ha_platform": "sensor",
        "ha_native_unit_of_measurement": PERCENTAGE,
        "ha_state_class": SensorStateClass.MEASUREMENT,
        "icon": "mdi:arrow-collapse-down",
        "writable": False,
        "parse_as_type": "float",
    },
    "pid3_o2_sekundarluft_maximum": {
        "hdg_node_id": "2624T",
        "translation_key": "pid3_o2_sekundarluft_maximum",
        "hdg_data_type": "2",
        "hdg_formatter": "iPERC",
        "ha_platform": "sensor",
        "ha_native_unit_of_measurement": PERCENTAGE,
        "ha_state_class": SensorStateClass.MEASUREMENT,
        "icon": "mdi:arrow-collapse-up",
        "writable": False,
        "parse_as_type": "float",
    },
    "rucklaufmischer_laufzeit_gesamt": {
        "hdg_node_id": "2805T",
        "translation_key": "rucklaufmischer_laufzeit_gesamt",
        "hdg_data_type": "2",
        "hdg_formatter": "iSEK",
        "ha_platform": "sensor",
        "ha_device_class": SensorDeviceClass.DURATION,
        "ha_native_unit_of_measurement": UnitOfTime.SECONDS,
        "ha_state_class": SensorStateClass.TOTAL_INCREASING,
        "icon": "mdi:timer-sync-outline",
        "writable": False,
        "parse_as_type": "float",
        "entity_category": EntityCategory.DIAGNOSTIC,
    },
    "pid_sollwert_rucklauf_spreizung_minimum": {
        "hdg_node_id": "2813T",
        "translation_key": "pid_sollwert_rucklauf_spreizung_minimum",
        "hdg_data_type": "2",
        "hdg_formatter": "iKELV",
        "ha_platform": "sensor",
        "ha_native_unit_of_measurement": UnitOfTemperature.KELVIN,
        "ha_state_class": SensorStateClass.MEASUREMENT,
        "icon": "mdi:thermometer-minus",
        "writable": False,
        "parse_as_type": "float",
    },
    "restwarmenutzung_puffer_bezug": {
        "hdg_node_id": "2816T",
        "translation_key": "restwarmenutzung_puffer_bezug",
        "hdg_data_type": "10",
        "hdg_formatter": None,
        "hdg_enum_type": "PUFFER_POS",
        "ha_platform": "sensor",
        "icon": "mdi:heat-wave",
        "writable": False,
        "parse_as_type": "enum_text",
    },
    "freigabe_kesseltemperatur": {
        "hdg_node_id": "2901T",
        "translation_key": "freigabe_kesseltemperatur",
        "hdg_data_type": "2",
        "hdg_formatter": "iTEMP",
        "ha_platform": "sensor",
        "ha_device_class": SensorDeviceClass.TEMPERATURE,
        "ha_native_unit_of_measurement": UnitOfTemperature.CELSIUS,
        "ha_state_class": SensorStateClass.MEASUREMENT,
        "icon": "mdi:thermometer-check",
        "writable": False,
        "parse_as_type": "float",
    },
    "freigabe_abgastemperatur": {
        "hdg_node_id": "2904T",
        "translation_key": "freigabe_abgastemperatur",
        "hdg_data_type": "2",
        "hdg_formatter": "iTEMP",
        "ha_platform": "sensor",
        "ha_device_class": SensorDeviceClass.TEMPERATURE,
        "ha_native_unit_of_measurement": UnitOfTemperature.CELSIUS,
        "ha_state_class": SensorStateClass.MEASUREMENT,
        "icon": "mdi:thermometer-high",
        "writable": False,
        "parse_as_type": "float",
    },
    "puffer_1_bezeichnung": {
        "hdg_node_id": "4020T",
        "translation_key": "puffer_1_bezeichnung",
        "hdg_data_type": "4",
        "hdg_formatter": None,
        "ha_platform": "sensor",
        "icon": "mdi:information-outline",
        "writable": False,
        "parse_as_type": "text",
        "entity_category": EntityCategory.DIAGNOSTIC,
    },
    "puffer_1_ladung_abbruch_temperatur_oben": {
        "hdg_node_id": "4033T",
        "translation_key": "puffer_1_ladung_abbruch_temperatur_oben",
        "hdg_data_type": "2",
        "hdg_formatter": "iTEMP",
        "ha_platform": "sensor",
        "ha_device_class": SensorDeviceClass.TEMPERATURE,
        "ha_native_unit_of_measurement": UnitOfTemperature.CELSIUS,
        "ha_state_class": SensorStateClass.MEASUREMENT,
        "icon": "mdi:thermometer-off",
        "writable": False,
        "parse_as_type": "float",
    },
    "puffer_1_fuhler_quelle": {
        "hdg_node_id": "4036T",
        "translation_key": "puffer_1_fuhler_quelle",
        "hdg_data_type": "10",
        "hdg_formatter": None,
        "hdg_enum_type": "PUFFER_POS",
        "ha_platform": "sensor",
        "icon": "mdi:thermometer-lines",
        "writable": False,
        "parse_as_type": "enum_text",
    },
    "puffer_1_energieberechnung_aktivieren": {
        "hdg_node_id": "4060T",
        "translation_key": "puffer_1_energieberechnung_aktivieren",
        "hdg_data_type": "10",
        "hdg_formatter": None,
        "hdg_enum_type": "YES/NO",
        "ha_platform": "sensor",
        "icon": "mdi:calculator-variant-outline",
        "writable": False,
        "parse_as_type": "enum_text",
    },
    "puffer_1_temperatur_kalt": {
        "hdg_node_id": "4061T",
        "translation_key": "puffer_1_temperatur_kalt",
        "hdg_data_type": "2",
        "hdg_formatter": "iTEMP",
        "ha_platform": "sensor",
        "ha_device_class": SensorDeviceClass.TEMPERATURE,
        "ha_native_unit_of_measurement": UnitOfTemperature.CELSIUS,
        "ha_state_class": SensorStateClass.MEASUREMENT,
        "icon": "mdi:thermometer-low",
        "writable": False,
        "parse_as_type": "float",
    },
    "puffer_1_temperatur_warm": {
        "hdg_node_id": "4062T",
        "translation_key": "puffer_1_temperatur_warm",
        "hdg_data_type": "2",
        "hdg_formatter": "iTEMP",
        "ha_platform": "sensor",
        "ha_device_class": SensorDeviceClass.TEMPERATURE,
        "ha_native_unit_of_measurement": UnitOfTemperature.CELSIUS,
        "ha_state_class": SensorStateClass.MEASUREMENT,
        "icon": "mdi:thermometer-high",
        "writable": False,
        "parse_as_type": "float",
    },
    "puffer_1_nachlegemenge_optimieren": {
        "hdg_node_id": "4064T",
        "translation_key": "puffer_1_nachlegemenge_optimieren",
        "hdg_data_type": "10",
        "hdg_formatter": None,
        "hdg_enum_type": "YES/NO",
        "ha_platform": "sensor",
        "icon": "mdi:basket-check-outline",
        "writable": False,
        "parse_as_type": "enum_text",
    },
    "puffer_1_grosse": {
        "hdg_node_id": "4065T",
        "translation_key": "puffer_1_grosse",
        "hdg_data_type": "1",
        "hdg_formatter": "iLITER",
        "ha_platform": "sensor",
        "ha_device_class": SensorDeviceClass.VOLUME,
        "ha_native_unit_of_measurement": UnitOfVolume.LITERS,
        "ha_state_class": None,
        "icon": "mdi:propane-tank",
        "writable": False,
        "parse_as_type": "float",
    },
    "puffer_1_umladesystem_aktivieren": {
        "hdg_node_id": "4070T",
        "translation_key": "puffer_1_umladesystem_aktivieren",
        "hdg_data_type": "10",
        "hdg_formatter": None,
        "hdg_enum_type": "YES/NO",
        "ha_platform": "sensor",
        "icon": "mdi:sync-circle",
        "writable": False,
        "parse_as_type": "enum_text",
    },
    "puffer_1_beladeventil_aktivieren": {
        "hdg_node_id": "4090T",
        "translation_key": "puffer_1_beladeventil_aktivieren",
        "hdg_data_type": "10",
        "hdg_formatter": None,
        "hdg_enum_type": "YES/NO",
        "ha_platform": "sensor",
        "icon": "mdi:valve-check",
        "writable": False,
        "parse_as_type": "enum_text",
    },
    "puffer_1_zonenventil_aktivieren": {
        "hdg_node_id": "4091T",
        "translation_key": "puffer_1_zonenventil_aktivieren",
        "hdg_data_type": "10",
        "hdg_formatter": None,
        "hdg_enum_type": "YES/NO",
        "ha_platform": "sensor",
        "icon": "mdi:valve-check",
        "writable": False,
        "parse_as_type": "enum_text",
    },
    "puffer_1_y2_ventil_aktivieren": {
        "hdg_node_id": "4095T",
        "translation_key": "puffer_1_y2_ventil_aktivieren",
        "hdg_data_type": "10",
        "hdg_formatter": None,
        "hdg_enum_type": "ON/OFF",
        "ha_platform": "sensor",
        "icon": "mdi:valve-check",
        "writable": False,
        "parse_as_type": "enum_text",
    },
    "puffer_art": {
        "hdg_node_id": "4099T",
        "translation_key": "puffer_art",
        "hdg_data_type": "10",
        "hdg_formatter": None,
        "hdg_enum_type": "PUFFER_ART",
        "ha_platform": "sensor",
        "icon": "mdi:propane-tank-outline",
        "writable": False,
        "parse_as_type": "enum_text",
    },
    "heizkreis_1_system": {
        "hdg_node_id": "6020T",
        "translation_key": "heizkreis_1_system",
        "hdg_data_type": "10",
        "hdg_formatter": None,
        "hdg_enum_type": "HK_SYSTEM",
        "ha_platform": "sensor",
        "icon": "mdi:radiator-disabled",
        "writable": False,
        "parse_as_type": "enum_text",
    },
    "hk1_bezeichnung": {
        "hdg_node_id": "6021T",
        "translation_key": "hk1_bezeichnung",
        "hdg_data_type": "4",
        "hdg_formatter": None,
        "ha_platform": "sensor",
        "icon": "mdi:label-outline",
        "writable": False,
        "parse_as_type": "text",
        "entity_category": EntityCategory.DIAGNOSTIC,
    },
    "hk1_soll_normal": {
        "hdg_node_id": "6022T",
        "translation_key": "hk1_soll_normal",
        "hdg_data_type": "2",
        "hdg_formatter": "iTEMP",
        "ha_platform": "number",
        "ha_device_class": SensorDeviceClass.TEMPERATURE,
        "ha_native_unit_of_measurement": UnitOfTemperature.CELSIUS,
        "ha_state_class": SensorStateClass.MEASUREMENT,
        "icon": "mdi:home-thermometer",
        "writable": True,
        "parse_as_type": "float",
        "entity_category": EntityCategory.CONFIG,
        "setter_type": "int",
        "setter_min_val": 0.0,
        "setter_max_val": 90.0,
        "setter_step": 1.0,
    },
    "hk1_soll_absenk": {
        "hdg_node_id": "6023T",
        "translation_key": "hk1_soll_absenk",
        "hdg_data_type": "2",
        "hdg_formatter": "iTEMP",
        "ha_platform": "number",
        "ha_device_class": SensorDeviceClass.TEMPERATURE,
        "ha_native_unit_of_measurement": UnitOfTemperature.CELSIUS,
        "ha_state_class": SensorStateClass.MEASUREMENT,
        "icon": "mdi:home-thermometer-outline",
        "writable": True,
        "parse_as_type": "float",
        "entity_category": EntityCategory.CONFIG,
        "setter_type": "int",
        "setter_min_val": 0.0,
        "setter_max_val": 90.0,
        "setter_step": 1.0,
    },
    "hk1_parallelverschiebung": {
        "hdg_node_id": "6024T",
        "translation_key": "hk1_parallelverschiebung",
        "hdg_data_type": "2",
        "hdg_formatter": "iKELV",
        "ha_platform": "number",
        "ha_native_unit_of_measurement": UnitOfTemperature.KELVIN,
        "ha_state_class": SensorStateClass.MEASUREMENT,
        "icon": "mdi:arrow-up-down",
        "writable": True,
        "parse_as_type": "float",
        "entity_category": EntityCategory.CONFIG,
        "setter_type": "int",
        "setter_min_val": -20.0,
        "setter_max_val": 20.0,
        "setter_step": 1.0,
    },
    "hk1_raumeinflussfaktor": {
        "hdg_node_id": "6025T",
        "translation_key": "hk1_raumeinflussfaktor",
        "hdg_data_type": "2",
        "hdg_formatter": None,
        "ha_platform": "sensor",
        "ha_state_class": SensorStateClass.MEASUREMENT,
        "icon": "mdi:home-import-outline",
        "writable": False,
        "parse_as_type": "float",
    },
    "hk1_steilheit": {
        "hdg_node_id": "6026T",
        "translation_key": "hk1_steilheit",
        "hdg_data_type": "2",
        "hdg_formatter": None,
        "ha_platform": "number",
        "ha_state_class": SensorStateClass.MEASUREMENT,
        "icon": "mdi:chart-line-variant",
        "writable": True,
        "parse_as_type": "float",
        "entity_category": EntityCategory.CONFIG,
        "setter_type": "float1",
        "setter_min_val": 0.1,
        "setter_max_val": 3.5,
        "setter_step": 0.1,
    },
    "hk1_vorlauftemperatur_minimum": {
        "hdg_node_id": "6027T",
        "translation_key": "hk1_vorlauftemperatur_minimum",
        "hdg_data_type": "2",
        "hdg_formatter": "iTEMP",
        "ha_platform": "sensor",
        "ha_device_class": SensorDeviceClass.TEMPERATURE,
        "ha_native_unit_of_measurement": UnitOfTemperature.CELSIUS,
        "ha_state_class": SensorStateClass.MEASUREMENT,
        "icon": "mdi:thermometer-minus",
        "writable": False,
        "parse_as_type": "float",
    },
    "hk1_vorlauftemperatur_maximum": {
        "hdg_node_id": "6028T",
        "translation_key": "hk1_vorlauftemperatur_maximum",
        "hdg_data_type": "2",
        "hdg_formatter": "iTEMP",
        "ha_platform": "sensor",
        "ha_device_class": SensorDeviceClass.TEMPERATURE,
        "ha_native_unit_of_measurement": UnitOfTemperature.CELSIUS,
        "ha_state_class": SensorStateClass.MEASUREMENT,
        "icon": "mdi:thermometer-plus",
        "writable": False,
        "parse_as_type": "float",
    },
    "hk1_raumeinheit_status": {
        "hdg_node_id": "6029T",
        "translation_key": "hk1_raumeinheit_status",
        "hdg_data_type": "10",
        "hdg_formatter": None,
        "hdg_enum_type": "RAUMEINHEIT",
        "ha_platform": "sensor",
        "icon": "mdi:remote",
        "writable": False,
        "parse_as_type": "enum_text",
        "entity_category": EntityCategory.DIAGNOSTIC,
    },
    "hk1_offset_raumfuhler": {
        "hdg_node_id": "6030T",
        "translation_key": "hk1_offset_raumfuhler",
        "hdg_data_type": "2",
        "hdg_formatter": "iKELV",
        "ha_platform": "sensor",
        "ha_native_unit_of_measurement": UnitOfTemperature.KELVIN,
        "ha_state_class": SensorStateClass.MEASUREMENT,
        "icon": "mdi:thermometer-offset",
        "writable": False,
        "parse_as_type": "float",
    },
    "hk1_warmequelle": {
        "hdg_node_id": "6039T",
        "translation_key": "hk1_warmequelle",
        "hdg_data_type": "10",
        "hdg_formatter": None,
        "hdg_enum_type": "QUELLE",
        "ha_platform": "sensor",
        "icon": "mdi:radiator-outline",
        "writable": False,
        "parse_as_type": "enum_text",
    },
    "hk1_mischerlaufzeit_maximum": {
        "hdg_node_id": "6041T",
        "translation_key": "hk1_mischerlaufzeit_maximum",
        "hdg_data_type": "2",
        "hdg_formatter": "iSEK",
        "ha_platform": "sensor",
        "ha_device_class": SensorDeviceClass.DURATION,
        "ha_native_unit_of_measurement": UnitOfTime.SECONDS,
        "ha_state_class": SensorStateClass.MEASUREMENT,
        "icon": "mdi:timer-settings-outline",
        "writable": False,
        "parse_as_type": "float",
    },
    "hk1_pumpe_ein_freigabetemperatur": {
        "hdg_node_id": "6046T",
        "translation_key": "hk1_pumpe_ein_freigabetemperatur",
        "hdg_data_type": "2",
        "hdg_formatter": "iTEMP",
        "ha_platform": "sensor",
        "ha_device_class": SensorDeviceClass.TEMPERATURE,
        "ha_native_unit_of_measurement": UnitOfTemperature.CELSIUS,
        "ha_state_class": SensorStateClass.MEASUREMENT,
        "icon": "mdi:pump-outline",
        "writable": False,
        "parse_as_type": "float",
    },
    "hk1_pumpe_aus_aussentemperatur": {
        "hdg_node_id": "6047T",
        "translation_key": "hk1_pumpe_aus_aussentemperatur",
        "hdg_data_type": "2",
        "hdg_formatter": "iTEMP",
        "ha_platform": "number",
        "ha_device_class": SensorDeviceClass.TEMPERATURE,
        "ha_native_unit_of_measurement": UnitOfTemperature.CELSIUS,
        "ha_state_class": SensorStateClass.MEASUREMENT,
        "icon": "mdi:pump-off-outline",
        "writable": True,
        "entity_category": EntityCategory.CONFIG,
        "parse_as_type": "float",
        "setter_type": "int",
        "setter_min_val": 0.0,
        "setter_max_val": 50.0,
        "setter_step": 1.0,
    },
    "hk1_frostschutz_temp": {
        "hdg_node_id": "6048T",
        "translation_key": "hk1_frostschutz_temp",
        "hdg_data_type": "2",
        "hdg_formatter": "iTEMP",
        "ha_platform": "sensor",
        "ha_device_class": SensorDeviceClass.TEMPERATURE,
        "ha_native_unit_of_measurement": UnitOfTemperature.CELSIUS,
        "ha_state_class": SensorStateClass.MEASUREMENT,
        "icon": "mdi:snowflake-thermometer",
        "writable": False,
        "parse_as_type": "float",
    },
    "hk1_eco_absenken_aus_aussentemperatur": {
        "hdg_node_id": "6049T",
        "translation_key": "hk1_eco_absenken_aus_aussentemperatur",
        "hdg_data_type": "2",
        "hdg_formatter": "iTEMP",
        "ha_platform": "number",
        "ha_device_class": SensorDeviceClass.TEMPERATURE,
        "ha_native_unit_of_measurement": UnitOfTemperature.CELSIUS,
        "ha_state_class": SensorStateClass.MEASUREMENT,
        "icon": "mdi:leaf-thermometer",
        "writable": True,
        "entity_category": EntityCategory.CONFIG,
        "parse_as_type": "float",
        "setter_type": "int",
        "setter_min_val": 0.0,
        "setter_max_val": 50.0,
        "setter_step": 1.0,
    },
    "heizgrenze_sommer": {
        "hdg_node_id": "6050T",
        "translation_key": "heizgrenze_sommer",
        "hdg_data_type": "2",
        "hdg_formatter": "iTEMP",
        "ha_platform": "sensor",
        "ha_device_class": SensorDeviceClass.TEMPERATURE,
        "ha_native_unit_of_measurement": UnitOfTemperature.CELSIUS,
        "ha_state_class": SensorStateClass.MEASUREMENT,
        "icon": "mdi:weather-sunny-alert",
        "writable": False,
        "parse_as_type": "float",
    },
    "heizgrenze_winter": {
        "hdg_node_id": "6051T",
        "translation_key": "heizgrenze_winter",
        "hdg_data_type": "2",
        "hdg_formatter": "iTEMP",
        "ha_platform": "sensor",
        "ha_device_class": SensorDeviceClass.TEMPERATURE,
        "ha_native_unit_of_measurement": UnitOfTemperature.CELSIUS,
        "ha_state_class": SensorStateClass.MEASUREMENT,
        "icon": "mdi:weather-snowy-heavy",
        "writable": False,
        "parse_as_type": "float",
    },
    "hk1_restwarme_aufnehmen": {
        "hdg_node_id": "6067T",
        "translation_key": "hk1_restwarme_aufnehmen",
        "hdg_data_type": "10",
        "hdg_formatter": None,
        "hdg_enum_type": "YES/NO",
        "ha_platform": "sensor",
        "icon": "mdi:heat-wave",  # Could be switch
        "writable": False,
        "parse_as_type": "enum_text",
    },
    "aussentemperatur": {
        "hdg_node_id": "20000T",
        "translation_key": "aussentemperatur",
        "hdg_data_type": "2",
        "hdg_formatter": "iTEMP",
        "ha_platform": "sensor",
        "ha_device_class": SensorDeviceClass.TEMPERATURE,
        "ha_native_unit_of_measurement": UnitOfTemperature.CELSIUS,
        "ha_state_class": SensorStateClass.MEASUREMENT,
        "icon": "mdi:thermometer",
        "writable": False,
        "parse_as_type": "float",
    },
    "software_version_touch": {
        "hdg_node_id": "20003T",
        "translation_key": "software_version_touch",
        "hdg_data_type": "2",
        "hdg_formatter": "iVERSION",
        "ha_platform": "sensor",
        "icon": "mdi:chip",
        "writable": False,
        "parse_as_type": "text",
        "entity_category": EntityCategory.DIAGNOSTIC,
    },
    "anlagenbezeichnung_sn": {
        "hdg_node_id": "20026T",
        "translation_key": "anlagenbezeichnung_sn",
        "hdg_data_type": "4",
        "hdg_formatter": None,
        "ha_platform": "sensor",
        "icon": "mdi:tag",
        "writable": False,
        "parse_as_type": "text",
        "entity_category": EntityCategory.DIAGNOSTIC,
    },
    "mac_adresse": {
        "hdg_node_id": "20031T",
        "translation_key": "mac_adresse",
        "hdg_data_type": "4",
        "hdg_formatter": None,
        "ha_platform": "sensor",
        "icon": "mdi:network-outline",
        "writable": False,
        "parse_as_type": "text",
        "entity_category": EntityCategory.DIAGNOSTIC,
    },
    "anlage_betriebsart": {
        "hdg_node_id": "20032T",
        "translation_key": "anlage_betriebsart",
        "hdg_data_type": "10",
        "hdg_formatter": None,
        "hdg_enum_type": "ANLAGE_BETRIEBSART",
        "ha_platform": "sensor",
        "icon": "mdi:home-automation",  # Could be select
        "writable": False,
        "parse_as_type": "enum_text",
        "entity_category": EntityCategory.DIAGNOSTIC,
    },
    "anlage_status_text": {
        "hdg_node_id": "20033T",
        "translation_key": "anlage_status_text",
        "hdg_data_type": "10",
        "hdg_formatter": None,
        "hdg_enum_type": "BETRIEBSART_CURRENT",
        "ha_platform": "sensor",
        "icon": "mdi:power-settings",
        "writable": False,
        "parse_as_type": "enum_text",
        "entity_category": EntityCategory.DIAGNOSTIC,
    },
    "software_version_fa": {
        "hdg_node_id": "20036T",
        "translation_key": "software_version_fa",
        "hdg_data_type": "2",
        "hdg_formatter": "iVERSION",
        "ha_platform": "sensor",
        "icon": "mdi:chip",
        "writable": False,
        "parse_as_type": "text",
        "entity_category": EntityCategory.DIAGNOSTIC,
    },
    "extra_version_info": {
        "hdg_node_id": "20037T",
        "translation_key": "extra_version_info",
        "hdg_data_type": "4",
        "hdg_formatter": None,
        "ha_platform": "sensor",
        "icon": "mdi:information-outline",
        "writable": False,
        "parse_as_type": "allow_empty_string",
        "entity_category": EntityCategory.DIAGNOSTIC,
    },
    "hydraulikschema_nummer": {
        "hdg_node_id": "20039T",
        "translation_key": "hydraulikschema_nummer",
        "hdg_data_type": "4",
        "hdg_formatter": None,
        "ha_platform": "sensor",
        "icon": "mdi:hydraulic-oil-level",
        "writable": False,
        "parse_as_type": "text",
        "entity_category": EntityCategory.DIAGNOSTIC,
    },
    "brennraumtemperatur_soll": {
        "hdg_node_id": "22000T",
        "translation_key": "brennraumtemperatur_soll",
        "hdg_data_type": "2",
        "hdg_formatter": "iTEMP",
        "ha_platform": "sensor",
        "ha_device_class": SensorDeviceClass.TEMPERATURE,
        "ha_native_unit_of_measurement": UnitOfTemperature.CELSIUS,
        "ha_state_class": SensorStateClass.MEASUREMENT,
        "icon": "mdi:thermometer-lines",
        "writable": False,
        "parse_as_type": "float",
    },
    "kessel_abgastemperatur_ist": {
        "hdg_node_id": "22001T",
        "translation_key": "kessel_abgastemperatur_ist",
        "hdg_data_type": "2",
        "hdg_formatter": "iTEMP",
        "ha_platform": "sensor",
        "ha_device_class": SensorDeviceClass.TEMPERATURE,
        "ha_native_unit_of_measurement": UnitOfTemperature.CELSIUS,
        "ha_state_class": SensorStateClass.MEASUREMENT,
        "icon": "mdi:thermometer-high",
        "writable": False,
        "parse_as_type": "float",
    },
    "kessel_restsauerstoff_ist": {
        "hdg_node_id": "22002T",
        "translation_key": "kessel_restsauerstoff_ist",
        "hdg_data_type": "2",
        "hdg_formatter": "iPERC",
        "ha_platform": "sensor",
        "ha_native_unit_of_measurement": PERCENTAGE,
        "ha_state_class": SensorStateClass.MEASUREMENT,
        "icon": "mdi:molecule-co2",
        "writable": False,
        "parse_as_type": "float",
    },
    "kesseltemperatur_ist": {
        "hdg_node_id": "22003T",
        "translation_key": "kesseltemperatur_ist",
        "hdg_data_type": "2",
        "hdg_formatter": "iTEMP",
        "ha_platform": "sensor",
        "ha_device_class": SensorDeviceClass.TEMPERATURE,
        "ha_native_unit_of_measurement": UnitOfTemperature.CELSIUS,
        "ha_state_class": SensorStateClass.MEASUREMENT,
        "icon": "mdi:thermometer",
        "writable": False,
        "parse_as_type": "float",
    },
    "kessel_rucklauftemperatur_ist": {
        "hdg_node_id": "22004T",
        "translation_key": "kessel_rucklauftemperatur_ist",
        "hdg_data_type": "2",
        "hdg_formatter": "iTEMP",
        "ha_platform": "sensor",
        "ha_device_class": SensorDeviceClass.TEMPERATURE,
        "ha_native_unit_of_measurement": UnitOfTemperature.CELSIUS,
        "ha_state_class": SensorStateClass.MEASUREMENT,
        "icon": "mdi:thermometer-water",
        "writable": False,
        "parse_as_type": "float",
    },
    "materialmenge_aktuell": {
        "hdg_node_id": "22005T",
        "translation_key": "materialmenge_aktuell",
        "hdg_data_type": "2",
        "hdg_formatter": "iPERC",
        "ha_platform": "sensor",
        "ha_native_unit_of_measurement": PERCENTAGE,
        "ha_state_class": SensorStateClass.MEASUREMENT,
        "icon": "mdi:gauge",
        "writable": False,
        "parse_as_type": "float",
    },
    "primarluftklappe_ist": {
        "hdg_node_id": "22008T",
        "translation_key": "primarluftklappe_ist",
        "hdg_data_type": "2",
        "hdg_formatter": "iPERC",
        "ha_platform": "sensor",
        "ha_native_unit_of_measurement": PERCENTAGE,
        "ha_state_class": SensorStateClass.MEASUREMENT,
        "icon": "mdi:valve",
        "writable": False,
        "parse_as_type": "float",
    },
    "sekundarluftklappe_ist": {
        "hdg_node_id": "22009T",
        "translation_key": "sekundarluftklappe_ist",
        "hdg_data_type": "2",
        "hdg_formatter": "iPERC",
        "ha_platform": "sensor",
        "ha_native_unit_of_measurement": PERCENTAGE,
        "ha_state_class": SensorStateClass.MEASUREMENT,
        "icon": "mdi:valve",
        "writable": False,
        "parse_as_type": "float",
    },
    "kessel_status": {
        "hdg_node_id": "22010T",
        "translation_key": "kessel_status",
        "hdg_data_type": "10",
        "hdg_formatter": None,
        "hdg_enum_type": "KESSELSTATUS",
        "ha_platform": "sensor",
        "icon": "mdi:fire",
        "writable": False,
        "parse_as_type": "enum_text",
        "entity_category": EntityCategory.DIAGNOSTIC,
    },
    "kessel_betriebsstunden": {
        "hdg_node_id": "22011T",
        "translation_key": "kessel_betriebsstunden",
        "hdg_data_type": "2",
        "hdg_formatter": "iSTD",
        "ha_platform": "sensor",
        "ha_device_class": SensorDeviceClass.DURATION,
        "ha_native_unit_of_measurement": UnitOfTime.HOURS,
        "ha_state_class": SensorStateClass.TOTAL_INCREASING,
        "icon": "mdi:timer-outline",
        "writable": False,
        "parse_as_type": "float",
        "entity_category": EntityCategory.DIAGNOSTIC,
    },
    "laufzeit_wt_reinigung": {
        "hdg_node_id": "22012T",
        "translation_key": "laufzeit_wt_reinigung",
        "hdg_data_type": "2",
        "hdg_formatter": "iSTD",
        "ha_platform": "sensor",
        "ha_device_class": SensorDeviceClass.DURATION,
        "ha_native_unit_of_measurement": UnitOfTime.HOURS,
        "ha_state_class": SensorStateClass.TOTAL_INCREASING,
        "icon": "mdi:broom",
        "writable": False,
        "parse_as_type": "float",
        "entity_category": EntityCategory.DIAGNOSTIC,
    },
    "laufzeit_entaschung": {
        "hdg_node_id": "22013T",
        "translation_key": "laufzeit_entaschung",
        "hdg_data_type": "2",
        "hdg_formatter": "iSTD",
        "ha_platform": "sensor",
        "ha_device_class": SensorDeviceClass.DURATION,
        "ha_native_unit_of_measurement": UnitOfTime.HOURS,
        "ha_state_class": SensorStateClass.TOTAL_INCREASING,
        "icon": "mdi:delete-sweep-outline",
        "writable": False,
        "parse_as_type": "float",
        "entity_category": EntityCategory.DIAGNOSTIC,
    },
    "laufzeit_hauptgeblase": {
        "hdg_node_id": "22014T",
        "translation_key": "laufzeit_hauptgeblase",
        "hdg_data_type": "2",
        "hdg_formatter": "iSTD",
        "ha_platform": "sensor",
        "ha_device_class": SensorDeviceClass.DURATION,
        "ha_native_unit_of_measurement": UnitOfTime.HOURS,
        "ha_state_class": SensorStateClass.TOTAL_INCREASING,
        "icon": "mdi:fan-clock",
        "writable": False,
        "parse_as_type": "float",
        "entity_category": EntityCategory.DIAGNOSTIC,
    },
    "laufzeit_zundgeblase": {
        "hdg_node_id": "22015T",
        "translation_key": "laufzeit_zundgeblase",
        "hdg_data_type": "2",
        "hdg_formatter": "iSTD",
        "ha_platform": "sensor",
        "ha_device_class": SensorDeviceClass.DURATION,
        "ha_native_unit_of_measurement": UnitOfTime.HOURS,
        "ha_state_class": SensorStateClass.TOTAL_INCREASING,
        "icon": "mdi:fan-plus",
        "writable": False,
        "parse_as_type": "float",
        "entity_category": EntityCategory.DIAGNOSTIC,
    },
    "anzahl_rostkippungen": {
        "hdg_node_id": "22016T",
        "translation_key": "anzahl_rostkippungen",
        "hdg_data_type": "2",
        "hdg_formatter": None,
        "ha_platform": "sensor",
        "ha_state_class": SensorStateClass.TOTAL_INCREASING,
        "icon": "mdi:recycle-variant",
        "writable": False,
        "parse_as_type": "int",
        "entity_category": EntityCategory.DIAGNOSTIC,
    },
    "primarluftklappe_soll": {
        "hdg_node_id": "22019T",
        "translation_key": "primarluftklappe_soll",
        "hdg_data_type": "2",
        "hdg_formatter": "iPERC",
        "ha_platform": "sensor",
        "ha_native_unit_of_measurement": PERCENTAGE,
        "ha_state_class": SensorStateClass.MEASUREMENT,
        "icon": "mdi:valve-closed",
        "writable": False,
        "parse_as_type": "float",
    },
    "kessel_haupt_betriebsart": {
        "hdg_node_id": "22020T",
        "translation_key": "kessel_haupt_betriebsart",
        "hdg_data_type": "10",
        "hdg_formatter": None,
        "hdg_enum_type": "KESSEL_HBA",
        "ha_platform": "sensor",
        "icon": "mdi:cogs",
        "writable": False,
        "parse_as_type": "enum_text",
        "entity_category": EntityCategory.DIAGNOSTIC,
    },
    "kessel_externe_anforderung": {
        "hdg_node_id": "22021T",
        "translation_key": "kessel_externe_anforderung",
        "hdg_data_type": "2",
        "hdg_formatter": "iPERC",
        "ha_platform": "sensor",
        "ha_native_unit_of_measurement": PERCENTAGE,
        "ha_state_class": SensorStateClass.MEASUREMENT,
        "icon": "mdi:call-made",
        "writable": False,
        "parse_as_type": "float",
    },
    "kesselvorlauf_solltemperatur": {
        "hdg_node_id": "22022T",
        "translation_key": "kesselvorlauf_solltemperatur",
        "hdg_data_type": "2",
        "hdg_formatter": "iTEMP",
        "ha_platform": "sensor",
        "ha_device_class": SensorDeviceClass.TEMPERATURE,
        "ha_native_unit_of_measurement": UnitOfTemperature.CELSIUS,
        "ha_state_class": SensorStateClass.MEASUREMENT,
        "icon": "mdi:thermometer-chevron-up",
        "writable": False,
        "parse_as_type": "float",
    },
    "kesselrucklauf_solltemperatur": {
        "hdg_node_id": "22023T",
        "translation_key": "kesselrucklauf_solltemperatur",
        "hdg_data_type": "2",
        "hdg_formatter": "iTEMP",
        "ha_platform": "sensor",
        "ha_device_class": SensorDeviceClass.TEMPERATURE,
        "ha_native_unit_of_measurement": UnitOfTemperature.CELSIUS,
        "ha_state_class": SensorStateClass.MEASUREMENT,
        "icon": "mdi:thermometer-water",
        "writable": False,
        "parse_as_type": "float",
    },
    "kesselleistung_ist": {
        "hdg_node_id": "22024T",
        "translation_key": "kesselleistung_ist",
        "hdg_data_type": "2",
        "hdg_formatter": "iPERC",
        "ha_platform": "sensor",
        "ha_device_class": SensorDeviceClass.POWER_FACTOR,
        "ha_native_unit_of_measurement": PERCENTAGE,
        "ha_state_class": SensorStateClass.MEASUREMENT,
        "icon": "mdi:fire-circle",
        "writable": False,
        "parse_as_type": "float",
    },
    "kessel_restlaufzeit_wartung": {
        "hdg_node_id": "22025T",
        "translation_key": "kessel_restlaufzeit_wartung",
        "hdg_data_type": "2",
        "hdg_formatter": "iSTD",
        "ha_platform": "sensor",
        "ha_device_class": SensorDeviceClass.DURATION,
        "ha_native_unit_of_measurement": UnitOfTime.HOURS,
        "ha_state_class": SensorStateClass.MEASUREMENT,
        "icon": "mdi:wrench-clock",
        "writable": False,
        "parse_as_type": "float",
        "entity_category": EntityCategory.DIAGNOSTIC,
    },
    "kessel_betriebsphase_text": {
        "hdg_node_id": "22026T",
        "translation_key": "kessel_betriebsphase_text",
        "hdg_data_type": "10",
        "hdg_formatter": None,
        "hdg_enum_type": "HK_BETRIEBSPHASE",
        "ha_platform": "sensor",
        "icon": "mdi:state-machine",
        "writable": False,
        "parse_as_type": "enum_text",
        "entity_category": EntityCategory.DIAGNOSTIC,
    },
    "kessel_wirkungsgrad": {
        "hdg_node_id": "22028T",
        "translation_key": "kessel_wirkungsgrad",
        "hdg_data_type": "2",
        "hdg_formatter": "iPERC",
        "ha_platform": "sensor",
        "ha_native_unit_of_measurement": PERCENTAGE,
        "ha_state_class": SensorStateClass.MEASUREMENT,
        "icon": "mdi:chart-bell-curve-cumulative",
        "writable": False,
        "parse_as_type": "float",
    },
    "kessel_ausbrandgrund": {
        "hdg_node_id": "22029T",
        "translation_key": "kessel_ausbrandgrund",
        "hdg_data_type": "10",
        "hdg_formatter": None,
        "hdg_enum_type": "AUSBRANDGRUND",
        "ha_platform": "sensor",
        "icon": "mdi:fire-alert",
        "writable": False,
        "parse_as_type": "enum_text",
        "entity_category": EntityCategory.DIAGNOSTIC,
    },
    "kessel_saugzuggeblase_ist": {
        "hdg_node_id": "22030T",
        "translation_key": "kessel_saugzuggeblase_ist",
        "hdg_data_type": "2",
        "hdg_formatter": "iPERC",
        "ha_platform": "sensor",
        "ha_native_unit_of_measurement": PERCENTAGE,
        "ha_state_class": SensorStateClass.MEASUREMENT,
        "icon": "mdi:fan",
        "writable": False,
        "parse_as_type": "float",
    },
    "kessel_unterdruck_ist": {
        "hdg_node_id": "22031T",
        "translation_key": "kessel_unterdruck_ist",
        "hdg_data_type": "2",
        "hdg_formatter": "iPASCAL",
        "ha_platform": "sensor",
        "ha_device_class": SensorDeviceClass.PRESSURE,
        "ha_native_unit_of_measurement": UnitOfPressure.PA,
        "ha_state_class": SensorStateClass.MEASUREMENT,
        "icon": "mdi:gauge-low",
        "writable": False,
        "parse_as_type": "float",
    },
    "sekundarluftklappe_soll": {
        "hdg_node_id": "22033T",
        "translation_key": "sekundarluftklappe_soll",
        "hdg_data_type": "2",
        "hdg_formatter": "iPERC",
        "ha_platform": "sensor",
        "ha_native_unit_of_measurement": PERCENTAGE,
        "ha_state_class": SensorStateClass.MEASUREMENT,
        "icon": "mdi:valve-closed",
        "writable": False,
        "parse_as_type": "float",
    },
    "betriebsstunden_rostmotor": {
        "hdg_node_id": "22037T",
        "translation_key": "betriebsstunden_rostmotor",
        "hdg_data_type": "2",
        "hdg_formatter": "iSTD",
        "ha_platform": "sensor",
        "ha_device_class": SensorDeviceClass.DURATION,
        "ha_native_unit_of_measurement": UnitOfTime.HOURS,
        "ha_state_class": SensorStateClass.TOTAL_INCREASING,
        "icon": "mdi:cog-counterclockwise",
        "writable": False,
        "parse_as_type": "float",
        "entity_category": EntityCategory.DIAGNOSTIC,
    },
    "betriebsstunden_stokerschnecke": {
        "hdg_node_id": "22038T",
        "translation_key": "betriebsstunden_stokerschnecke",
        "hdg_data_type": "2",
        "hdg_formatter": "iSTD",
        "ha_platform": "sensor",
        "ha_device_class": SensorDeviceClass.DURATION,
        "ha_native_unit_of_measurement": UnitOfTime.HOURS,
        "ha_state_class": SensorStateClass.TOTAL_INCREASING,
        "icon": "mdi:screw-lag",
        "writable": False,
        "parse_as_type": "float",
        "entity_category": EntityCategory.DIAGNOSTIC,
    },
    "betriebsstunden_ascheschnecke": {
        "hdg_node_id": "22039T",
        "translation_key": "betriebsstunden_ascheschnecke",
        "hdg_data_type": "2",
        "hdg_formatter": "iSTD",
        "ha_platform": "sensor",
        "ha_device_class": SensorDeviceClass.DURATION,
        "ha_native_unit_of_measurement": UnitOfTime.HOURS,
        "ha_state_class": SensorStateClass.TOTAL_INCREASING,
        "icon": "mdi:screw-lag",
        "writable": False,
        "parse_as_type": "float",
        "entity_category": EntityCategory.DIAGNOSTIC,
    },
    "restlaufzeit_schornsteinfeger": {
        "hdg_node_id": "22040T",
        "translation_key": "restlaufzeit_schornsteinfeger",
        "hdg_data_type": "2",
        "hdg_formatter": "iMIN",
        "ha_platform": "sensor",
        "ha_device_class": SensorDeviceClass.DURATION,
        "ha_native_unit_of_measurement": UnitOfTime.MINUTES,
        "ha_state_class": SensorStateClass.MEASUREMENT,
        "icon": "mdi:account-hard-hat-outline",
        "writable": False,
        "parse_as_type": "float",
        "entity_category": EntityCategory.DIAGNOSTIC,
    },
    "kessel_typ_info_leer": {
        "hdg_node_id": "22041T",
        "translation_key": "kessel_typ_info_leer",
        "hdg_data_type": "4",
        "hdg_formatter": None,
        "ha_platform": "sensor",
        "icon": "mdi:information-off-outline",
        "writable": False,
        "parse_as_type": "allow_empty_string",
        "entity_category": EntityCategory.DIAGNOSTIC,
    },
    "kessel_rucklaufmischer": {
        "hdg_node_id": "22043T",
        "translation_key": "kessel_rucklaufmischer",
        "hdg_data_type": "2",
        "hdg_formatter": "iPERC",
        "ha_platform": "sensor",
        "ha_native_unit_of_measurement": PERCENTAGE,
        "ha_state_class": SensorStateClass.MEASUREMENT,
        "icon": "mdi:valve-open",
        "writable": False,
        "parse_as_type": "float",
    },
    "abgasleitwert_ist": {
        "hdg_node_id": "22044T",
        "translation_key": "abgasleitwert_ist",
        "hdg_data_type": "2",
        "hdg_formatter": "iKELV",
        "ha_platform": "sensor",
        "ha_native_unit_of_measurement": UnitOfTemperature.KELVIN,
        "ha_state_class": SensorStateClass.MEASUREMENT,
        "icon": "mdi:delta",
        "writable": False,
        "parse_as_type": "float",
    },
    "kessel_restsauerstoff_korr": {
        "hdg_node_id": "22045T",
        "translation_key": "kessel_restsauerstoff_korr",
        "hdg_data_type": "2",
        "hdg_formatter": "iPERC",
        "ha_platform": "sensor",
        "ha_native_unit_of_measurement": PERCENTAGE,
        "ha_state_class": SensorStateClass.MEASUREMENT,
        "icon": "mdi:molecule-co2",
        "writable": False,
        "parse_as_type": "float",
    },
    "primarluft_korrektur_o2": {
        "hdg_node_id": "22046T",
        "translation_key": "primarluft_korrektur_o2",
        "hdg_data_type": "10",
        "hdg_formatter": None,
        "hdg_enum_type": "YES/NO",
        "ha_platform": "sensor",
        "icon": "mdi:air-filter",
        "writable": False,
        "parse_as_type": "enum_text",
    },
    "abgasleitwert_soll": {
        "hdg_node_id": "22049T",
        "translation_key": "abgasleitwert_soll",
        "hdg_data_type": "2",
        "hdg_formatter": "iKELV",
        "ha_platform": "sensor",
        "ha_native_unit_of_measurement": UnitOfTemperature.KELVIN,
        "ha_state_class": SensorStateClass.MEASUREMENT,
        "icon": "mdi:delta",
        "writable": False,
        "parse_as_type": "float",
    },
    "kessel_o2_sollwert": {
        "hdg_node_id": "22050T",
        "translation_key": "kessel_o2_sollwert",
        "hdg_data_type": "2",
        "hdg_formatter": "iPERC",
        "ha_platform": "sensor",
        "ha_native_unit_of_measurement": PERCENTAGE,
        "ha_state_class": SensorStateClass.MEASUREMENT,
        "icon": "mdi:target-variant",
        "writable": False,
        "parse_as_type": "float",
    },
    "kessel_nachlegemenge": {
        "hdg_node_id": "22052T",
        "translation_key": "kessel_nachlegemenge",
        "hdg_data_type": "2",
        "hdg_formatter": "iPERC",
        "ha_platform": "sensor",
        "ha_native_unit_of_measurement": PERCENTAGE,
        "ha_state_class": SensorStateClass.MEASUREMENT,
        "icon": "mdi:basket-fill",
        "writable": False,
        "parse_as_type": "float",
    },
    "kessel_nachlegezeitpunkt_2": {
        "hdg_node_id": "22053T",
        "translation_key": "kessel_nachlegezeitpunkt_2",
        "hdg_data_type": "2",
        "hdg_formatter": "iRSINLM",
        "ha_platform": "sensor",
        "ha_device_class": SensorDeviceClass.TIMESTAMP,
        "icon": "mdi:clock-alert-outline",
        "writable": False,
        "parse_as_type": "hdg_datetime_or_text",
        "entity_category": EntityCategory.DIAGNOSTIC,
    },
    "kessel_energieverbrauch_tag_gesamt": {
        "hdg_node_id": "22054T",
        "translation_key": "kessel_energieverbrauch_tag_gesamt",
        "hdg_data_type": "2",
        "hdg_formatter": "iKWH",
        "ha_platform": "sensor",
        "ha_device_class": SensorDeviceClass.ENERGY,
        "ha_native_unit_of_measurement": UnitOfEnergy.KILO_WATT_HOUR,
        "ha_state_class": SensorStateClass.TOTAL_INCREASING,
        "icon": "mdi:lightning-bolt",
        "writable": False,
        "parse_as_type": "float",
        "entity_category": EntityCategory.DIAGNOSTIC,
    },
    "kessel_nachlegebedarf": {
        "hdg_node_id": "22057T",
        "translation_key": "kessel_nachlegebedarf",
        "hdg_data_type": "2",
        "hdg_formatter": "iPERC",
        "ha_platform": "sensor",
        "ha_native_unit_of_measurement": PERCENTAGE,
        "ha_state_class": SensorStateClass.MEASUREMENT,
        "icon": "mdi:basket-unfill",
        "writable": False,
        "parse_as_type": "float",
    },
    "kessel_nachlegen_anzeige_text": {
        "hdg_node_id": "22062T",
        "translation_key": "kessel_nachlegen_anzeige_text",
        "hdg_data_type": "10",
        "hdg_formatter": None,
        "hdg_enum_type": "NACHLEGEN_ANZEIGE",
        "ha_platform": "sensor",
        "icon": "mdi:basket-alert-outline",
        "writable": False,
        "parse_as_type": "enum_text",
        "entity_category": EntityCategory.DIAGNOSTIC,
    },
    "zeit_kesseluberhitzung_10_abbrande_std": {
        "hdg_node_id": "22064T",
        "translation_key": "zeit_kesseluberhitzung_10_abbrande_std",
        "hdg_data_type": "2",
        "hdg_formatter": "iSTD",
        "ha_platform": "sensor",
        "ha_device_class": SensorDeviceClass.DURATION,
        "ha_native_unit_of_measurement": UnitOfTime.HOURS,
        "ha_state_class": SensorStateClass.TOTAL_INCREASING,
        "icon": "mdi:timer-alert-outline",
        "writable": False,
        "parse_as_type": "float",
        "entity_category": EntityCategory.DIAGNOSTIC,
    },
    "zeit_kesseluberhitzung_10_abbrande_prozent": {
        "hdg_node_id": "22065T",
        "translation_key": "zeit_kesseluberhitzung_10_abbrande_prozent",
        "hdg_data_type": "2",
        "hdg_formatter": "iPERC",
        "ha_platform": "sensor",
        "ha_native_unit_of_measurement": PERCENTAGE,
        "ha_state_class": SensorStateClass.MEASUREMENT,
        "icon": "mdi:alert-circle-check-outline",
        "writable": False,
        "parse_as_type": "float",
        "entity_category": EntityCategory.DIAGNOSTIC,
    },
    "zeit_kesseluberhitzung_gesamt_std": {
        "hdg_node_id": "22066T",
        "translation_key": "zeit_kesseluberhitzung_gesamt_std",
        "hdg_data_type": "2",
        "hdg_formatter": "iSTD",
        "ha_platform": "sensor",
        "ha_device_class": SensorDeviceClass.DURATION,
        "ha_native_unit_of_measurement": UnitOfTime.HOURS,
        "ha_state_class": SensorStateClass.TOTAL_INCREASING,
        "icon": "mdi:timer-alert",
        "writable": False,
        "parse_as_type": "float",
        "entity_category": EntityCategory.DIAGNOSTIC,
    },
    "zeit_kesseluberhitzung_gesamt_prozent": {
        "hdg_node_id": "22067T",
        "translation_key": "zeit_kesseluberhitzung_gesamt_prozent",
        "hdg_data_type": "2",
        "hdg_formatter": "iPERC",
        "ha_platform": "sensor",
        "ha_native_unit_of_measurement": PERCENTAGE,
        "ha_state_class": SensorStateClass.MEASUREMENT,
        "icon": "mdi:alert-circle-check",
        "writable": False,
        "parse_as_type": "float",
        "entity_category": EntityCategory.DIAGNOSTIC,
    },
    "stillstandszeit_soll": {
        "hdg_node_id": "22068T",
        "translation_key": "stillstandszeit_soll",
        "hdg_data_type": "2",
        "hdg_formatter": "iSTD",
        "ha_platform": "sensor",
        "ha_device_class": SensorDeviceClass.DURATION,
        "ha_native_unit_of_measurement": UnitOfTime.HOURS,
        "ha_state_class": SensorStateClass.MEASUREMENT,
        "icon": "mdi:timer-sand",
        "writable": False,
        "parse_as_type": "float",
    },
    "kessel_warmemenge_gesamt": {
        "hdg_node_id": "22069T",
        "translation_key": "kessel_warmemenge_gesamt",
        "hdg_data_type": "2",
        "hdg_formatter": "iMWH",
        "ha_platform": "sensor",
        "ha_device_class": SensorDeviceClass.ENERGY,
        "ha_native_unit_of_measurement": UnitOfEnergy.MEGA_WATT_HOUR,
        "ha_state_class": SensorStateClass.TOTAL_INCREASING,
        "icon": "mdi:lightning-bolt-circle",
        "writable": False,
        "parse_as_type": "float",
        "entity_category": EntityCategory.DIAGNOSTIC,
    },
    "kessel_stillstandszeit": {
        "hdg_node_id": "22070T",
        "translation_key": "kessel_stillstandszeit",
        "hdg_data_type": "2",
        "hdg_formatter": "iSTD",
        "ha_platform": "sensor",
        "ha_device_class": SensorDeviceClass.DURATION,
        "ha_native_unit_of_measurement": UnitOfTime.HOURS,
        "ha_state_class": SensorStateClass.TOTAL_INCREASING,
        "icon": "mdi:timer-sand-complete",
        "writable": False,
        "parse_as_type": "float",
        "entity_category": EntityCategory.DIAGNOSTIC,
    },
    "angeforderte_temperatur_abnehmer": {
        "hdg_node_id": "22098T",
        "translation_key": "angeforderte_temperatur_abnehmer",
        "hdg_data_type": "2",
        "hdg_formatter": "iTEMP",
        "ha_platform": "sensor",
        "ha_device_class": SensorDeviceClass.TEMPERATURE,
        "ha_native_unit_of_measurement": UnitOfTemperature.CELSIUS,
        "ha_state_class": SensorStateClass.MEASUREMENT,
        "icon": "mdi:thermometer-alert",
        "writable": False,
        "parse_as_type": "float",
    },
    "puffer_temperatur_oben": {
        "hdg_node_id": "24000T",
        "translation_key": "puffer_temperatur_oben",
        "hdg_data_type": "2",
        "hdg_formatter": "iTEMP",
        "ha_platform": "sensor",
        "ha_device_class": SensorDeviceClass.TEMPERATURE,
        "ha_native_unit_of_measurement": UnitOfTemperature.CELSIUS,
        "ha_state_class": SensorStateClass.MEASUREMENT,
        "icon": "mdi:coolant-temperature",
        "writable": False,
        "parse_as_type": "float",
    },
    "puffer_temperatur_mitte": {
        "hdg_node_id": "24001T",
        "translation_key": "puffer_temperatur_mitte",
        "hdg_data_type": "2",
        "hdg_formatter": "iTEMP",
        "ha_platform": "sensor",
        "ha_device_class": SensorDeviceClass.TEMPERATURE,
        "ha_native_unit_of_measurement": UnitOfTemperature.CELSIUS,
        "ha_state_class": SensorStateClass.MEASUREMENT,
        "icon": "mdi:coolant-temperature",
        "writable": False,
        "parse_as_type": "float",
    },
    "puffer_temperatur_unten": {
        "hdg_node_id": "24002T",
        "translation_key": "puffer_temperatur_unten",
        "hdg_data_type": "2",
        "hdg_formatter": "iTEMP",
        "ha_platform": "sensor",
        "ha_device_class": SensorDeviceClass.TEMPERATURE,
        "ha_native_unit_of_measurement": UnitOfTemperature.CELSIUS,
        "ha_state_class": SensorStateClass.MEASUREMENT,
        "icon": "mdi:coolant-temperature",
        "writable": False,
        "parse_as_type": "float",
    },
    "puffer_soll_oben": {
        "hdg_node_id": "24004T",
        "translation_key": "puffer_soll_oben",
        "hdg_data_type": "2",
        "hdg_formatter": "iTEMP",
        "ha_platform": "sensor",
        "ha_device_class": SensorDeviceClass.TEMPERATURE,
        "ha_native_unit_of_measurement": UnitOfTemperature.CELSIUS,
        "ha_state_class": SensorStateClass.MEASUREMENT,
        "icon": "mdi:coolant-temperature",
        "writable": False,
        "parse_as_type": "float",
    },
    "puffer_rucklauf_soll": {
        "hdg_node_id": "24006T",
        "translation_key": "puffer_rucklauf_soll",
        "hdg_data_type": "2",
        "hdg_formatter": "iTEMP",
        "ha_platform": "sensor",
        "ha_device_class": SensorDeviceClass.TEMPERATURE,
        "ha_native_unit_of_measurement": UnitOfTemperature.CELSIUS,
        "ha_state_class": SensorStateClass.MEASUREMENT,
        "icon": "mdi:coolant-temperature",
        "writable": False,
        "parse_as_type": "float",
    },
    "puffer_status": {
        "hdg_node_id": "24015T",
        "translation_key": "puffer_status",
        "hdg_data_type": "10",
        "hdg_formatter": None,
        "hdg_enum_type": "PUFFER_ZUSTAND",
        "ha_platform": "sensor",
        "icon": "mdi:propane-tank-outline",
        "writable": False,
        "parse_as_type": "enum_text",
        "entity_category": EntityCategory.DIAGNOSTIC,
    },
    "puffer_energie_max": {
        "hdg_node_id": "24016T",
        "translation_key": "puffer_energie_max",
        "hdg_data_type": "2",
        "hdg_formatter": "iKWH",
        "ha_platform": "sensor",
        "ha_device_class": SensorDeviceClass.ENERGY,
        "ha_native_unit_of_measurement": UnitOfEnergy.KILO_WATT_HOUR,
        "ha_state_class": None,
        "icon": "mdi:battery-arrow-up",
        "writable": False,
        "parse_as_type": "float",
    },
    "puffer_energie_aktuell": {
        "hdg_node_id": "24017T",
        "translation_key": "puffer_energie_aktuell",
        "hdg_data_type": "2",
        "hdg_formatter": "iKWH",
        "ha_platform": "sensor",
        "ha_native_unit_of_measurement": UnitOfEnergy.KILO_WATT_HOUR,
        "ha_state_class": SensorStateClass.MEASUREMENT,
        "icon": "mdi:battery-charging",
        "writable": False,
        "parse_as_type": "float",
    },
    "puffer_ladezustand_alt": {
        "hdg_node_id": "24019T",
        "translation_key": "puffer_ladezustand_alt",
        "hdg_data_type": "2",
        "hdg_formatter": "iPERC",
        "ha_platform": "sensor",
        "ha_device_class": SensorDeviceClass.BATTERY,
        "ha_native_unit_of_measurement": PERCENTAGE,
        "ha_state_class": SensorStateClass.MEASUREMENT,
        "icon": "mdi:battery-70",
        "writable": False,
        "parse_as_type": "float",
    },
    "puffer_energie_gesamt_zahler": {
        "hdg_node_id": "24020T",
        "translation_key": "puffer_energie_gesamt_zahler",
        "hdg_data_type": "2",
        "hdg_formatter": "iKWH",
        "ha_platform": "sensor",
        "ha_device_class": SensorDeviceClass.ENERGY,
        "ha_native_unit_of_measurement": UnitOfEnergy.KILO_WATT_HOUR,
        "ha_state_class": SensorStateClass.TOTAL_INCREASING,
        "icon": "mdi:counter",
        "writable": False,
        "parse_as_type": "float",
        "entity_category": EntityCategory.DIAGNOSTIC,
    },
    "puffer_energie_ist": {
        "hdg_node_id": "24021T",
        "translation_key": "puffer_energie_ist",
        "hdg_data_type": "2",
        "hdg_formatter": "iKWH",
        "ha_platform": "sensor",
        "ha_native_unit_of_measurement": UnitOfEnergy.KILO_WATT_HOUR,
        "ha_state_class": SensorStateClass.MEASUREMENT,
        "icon": "mdi:battery-heart-variant",
        "writable": False,
        "parse_as_type": "float",
    },
    "puffer_energie_aufnehmbar": {
        "hdg_node_id": "24022T",
        "translation_key": "puffer_energie_aufnehmbar",
        "hdg_data_type": "2",
        "hdg_formatter": "iKWH",
        "ha_platform": "sensor",
        "ha_native_unit_of_measurement": UnitOfEnergy.KILO_WATT_HOUR,
        "ha_state_class": SensorStateClass.MEASUREMENT,
        "icon": "mdi:battery-plus-variant",
        "writable": False,
        "parse_as_type": "float",
    },
    "puffer_ladezustand": {
        "hdg_node_id": "24023T",
        "translation_key": "puffer_ladezustand",
        "hdg_data_type": "2",
        "hdg_formatter": "iPERC",
        "ha_platform": "sensor",
        "ha_device_class": SensorDeviceClass.BATTERY,
        "ha_native_unit_of_measurement": PERCENTAGE,
        "ha_state_class": SensorStateClass.MEASUREMENT,
        "icon": "mdi:battery-charging-70",
        "writable": False,
        "parse_as_type": "float",
    },
    "puffer_vorlauf_extern": {
        "hdg_node_id": "24098T",
        "translation_key": "puffer_vorlauf_extern",
        "hdg_data_type": "2",
        "hdg_formatter": "iTEMP",
        "ha_platform": "sensor",
        "ha_device_class": SensorDeviceClass.TEMPERATURE,
        "ha_native_unit_of_measurement": UnitOfTemperature.CELSIUS,
        "ha_state_class": SensorStateClass.MEASUREMENT,
        "icon": "mdi:thermometer-chevron-up",
        "writable": False,
        "parse_as_type": "float",
    },
    "puffer_rucklauf_extern": {
        "hdg_node_id": "24099T",
        "translation_key": "puffer_rucklauf_extern",
        "hdg_data_type": "2",
        "hdg_formatter": "iTEMP",
        "ha_platform": "sensor",
        "ha_device_class": SensorDeviceClass.TEMPERATURE,
        "ha_native_unit_of_measurement": UnitOfTemperature.CELSIUS,
        "ha_state_class": SensorStateClass.MEASUREMENT,
        "icon": "mdi:thermometer-chevron-down",
        "writable": False,
        "parse_as_type": "float",
    },
    "hk1_vorlauftemperatur_ist": {
        "hdg_node_id": "26000T",
        "translation_key": "hk1_vorlauftemperatur_ist",
        "hdg_data_type": "2",
        "hdg_formatter": "iTEMP",
        "ha_platform": "sensor",
        "ha_device_class": SensorDeviceClass.TEMPERATURE,
        "ha_native_unit_of_measurement": UnitOfTemperature.CELSIUS,
        "ha_state_class": SensorStateClass.MEASUREMENT,
        "icon": "mdi:radiator",
        "writable": False,
        "parse_as_type": "float",
    },
    "hk1_temp_quelle_status_wert": {
        "hdg_node_id": "26004T",
        "translation_key": "hk1_temp_quelle_status_wert",
        "hdg_data_type": "2",
        "hdg_formatter": None,
        "ha_platform": "sensor",
        "ha_state_class": SensorStateClass.MEASUREMENT,
        "icon": "mdi:thermometer-lines",
        "writable": False,
        "parse_as_type": "float",
    },
    "hk1_mischer_status_text": {
        "hdg_node_id": "26007T",
        "translation_key": "hk1_mischer_status_text",
        "hdg_data_type": "10",
        "hdg_formatter": None,
        "hdg_enum_type": "AUS/AUF/ZU/STOERUNG",
        "ha_platform": "sensor",
        "icon": "mdi:valve-settings",
        "writable": False,
        "parse_as_type": "enum_text",
        "entity_category": EntityCategory.DIAGNOSTIC,
    },
    "hk1_pumpe_status_text": {
        "hdg_node_id": "26008T",
        "translation_key": "hk1_pumpe_status_text",
        "hdg_data_type": "10",
        "hdg_formatter": None,
        "hdg_enum_type": "OFF/ON/STOERUNG",
        "ha_platform": "sensor",
        "icon": "mdi:pump",
        "writable": False,
        "parse_as_type": "enum_text",
        "entity_category": EntityCategory.DIAGNOSTIC,
    },
    "hk1_aktuelle_betriebsart": {
        "hdg_node_id": "26011T",
        "translation_key": "hk1_aktuelle_betriebsart",
        "hdg_data_type": "10",
        "hdg_formatter": None,
        "hdg_enum_type": "HEIZKREIS_CURRENT",
        "ha_platform": "sensor",
        "icon": "mdi:home-thermometer-outline",
        "writable": False,
        "parse_as_type": "enum_text",
        "entity_category": EntityCategory.DIAGNOSTIC,
    },
    "hk1_vorlauftemperatur_soll": {
        "hdg_node_id": "26099T",
        "translation_key": "hk1_vorlauftemperatur_soll",
        "hdg_data_type": "2",
        "hdg_formatter": "iTEMP",
        "ha_platform": "sensor",
        "ha_device_class": SensorDeviceClass.TEMPERATURE,
        "ha_native_unit_of_measurement": UnitOfTemperature.CELSIUS,
        "ha_state_class": SensorStateClass.MEASUREMENT,
        "icon": "mdi:radiator",
        "writable": False,
        "parse_as_type": "float",
    },
    # Add more sensor definitions here as needed, following the SensorDefinition structure.
}

# Service names used for registering and calling integration-specific services
SERVICE_SET_NODE_VALUE: Final = "set_node_value"
SERVICE_GET_NODE_VALUE: Final = "get_node_value"

# Attribute names used in service calls
ATTR_NODE_ID: Final = "node_id"
ATTR_VALUE: Final = "value"

# Fixed device information for HA device registry
MANUFACTURER: Final = "HDG Bavaria GmbH"
MODEL_PREFIX: Final = "HDG"  # Used if specific model cannot be determined from API
