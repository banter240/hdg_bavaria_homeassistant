<div align="center">

# HDG Bavaria Boiler Integration for Home Assistant 🏭

<br>

[![Latest Release](https://img.shields.io/github/v/release/banter240/hdg_bavaria_homeassistant?style=for-the-badge&color=2ea043&logo=github)](https://github.com/banter240/hdg_bavaria_homeassistant/releases/latest)
[![Dev Release](https://img.shields.io/github/v/release/banter240/hdg_bavaria_homeassistant?include_prereleases&label=dev&style=for-the-badge&color=orange&logo=github)](https://github.com/banter240/hdg_bavaria_homeassistant/releases)
[![Downloads](https://img.shields.io/github/downloads/banter240/hdg_bavaria_homeassistant/total?style=for-the-badge&color=green&logo=github)](https://github.com/banter240/hdg_bavaria_homeassistant/releases)
[![HACS Custom](https://img.shields.io/badge/HACS-Custom-41BDF5?style=for-the-badge&logo=home-assistant)](https://github.com/hacs/integration)
[![License](https://img.shields.io/github/license/banter240/hdg_bavaria_homeassistant?style=for-the-badge&color=blue)](LICENSE)

[![Discussions](https://img.shields.io/github/discussions/banter240/hdg_bavaria_homeassistant?style=for-the-badge&logo=github&color=7289DA)](https://github.com/banter240/hdg_bavaria_homeassistant/discussions)
[![Open Issues](https://img.shields.io/github/issues/banter240/hdg_bavaria_homeassistant?style=for-the-badge&color=red&logo=github)](https://github.com/banter240/hdg_bavaria_homeassistant/issues)
[![Stars](https://img.shields.io/github/stars/banter240/hdg_bavaria_homeassistant?style=for-the-badge&color=yellow&logo=github)](https://github.com/banter240/hdg_bavaria_homeassistant/stargazers)

<br>

<a href="https://buymeacoffee.com/banter240" target="_blank"><img src="https://cdn.buymeacoffee.com/buttons/v2/default-yellow.png" alt="Buy Me A Coffee" style="height: 50px !important;width: 181px !important;" ></a>

<br>

**A local-first Home Assistant integration for HDG Bavaria pellet, wood-chip and biomass boilers.**

</div>

<br>

---

<br>

<div align="center">

**[Overview](#overview)** • **[Features](#features)** • **[Component Support](#component-support)** • **[Architecture](#architecture)**<br>**[Installation](#installation)** • **[Configuration](#configuration)** • **[Entities](#entities--controls)** • **[Services](#services)**<br>**[Constraints](#known-constraints)** • **[Troubleshooting](#troubleshooting)** • **[FAQ](#frequently-asked-questions-faq)** • **[Docs](#documentation)** • **[☕ Support](#support-the-project)**

</div>

<br>

---

<br>

## Overview

This custom integration brings your HDG Bavaria boiler (Euro, K-series, Compact, etc.) into Home Assistant using the **local HTTP web interface** — no cloud, no official SDK required.

It is designed to work reliably with the relatively weak built-in web server of the boiler controller through smart polling, priority queuing, and only requesting data for entities you actually use.

> [!NOTE]
> **Local Only:**
> All communication happens directly on your local network. No internet connection to HDG or third parties is needed for core functionality.

<br>

---

<br>

## Features

- **Efficient Grouped Polling**
  - 5 configurable polling groups with different intervals.
  - Only nodes for *currently enabled* entities are polled.
  - Dynamic node selection via entity registry sync.

- **Robust Control**
  - Writable Number and Select entities for setpoints and modes.
  - Optimistic updates + debounce + automatic rollback on failure.
  - Preemption: user sets take priority over background polling.

- **Component Groups**
  - Optional hardware (HK2–HK6, WW2, Solar, Puffer 2, Netzpumpen 1–3, External heat source, Lager) is disabled by default for a clean UI.
  - Enable exactly what you have via the rich options flow.

- **Configurable Puffer Middle Sensors**
  - Optionally provide node IDs for additional buffer middle temperatures (oben/unten).
  - Solves differences in wiring between installations.

- **Advanced Architecture**
  - Auto protocol detection (V2 modern `nodes=...T` vs legacy V1 indexed form).
  - Dedicated API Access Manager with priority queue (HIGH for sets).
  - Full optimistic state management.
  - Automatic fallback + recovery when boiler is offline.
  - Maintenance mode (global kill switch).

- **Extras**
  - Raw `set_node_value` / `get_node_value` services.
  - Excellent German + English translations.
  - Comprehensive diagnostics export.
  - Detailed logging categories.

---

<br>

## Component Support

| Component       | Toggle Key         | Default | Description |
|-----------------|--------------------|---------|-------------|
| Heating Circuit 1 | (always)          | On     | Primary heating circuit |
| Heating Circuits 2–6 | `enable_hkX`     | Off    | Additional heating circuits |
| Hot Water 1     | `enable_ww1`       | Off    | First domestic hot water circuit |
| Hot Water 2     | `enable_ww2`       | Off    | Second domestic hot water circuit |
| Buffer 2        | `enable_puffer_2`  | Off    | Secondary buffer storage |
| Solar           | `enable_solar`     | Off    | Solar thermal collector & pumps |
| Network Pumps 1–3 | `enable_netzpumpe_X` | Off  | District heating / net pumps |
| External Heat Source | `enable_ext_wq` | Off | External heat source (e.g. heat pump) |
| Pellet Storage  | `enable_lager`     | Off    | Detailed pellet storage monitoring (total consumption, since last fill, etc.) |

All component entities start disabled by default. Enable the ones you need in the integration options.

---

<br>

## Key Highlights

### Configurable Puffer Middle Sensors

Some installations have additional temperature sensors in the middle of the buffer. You can now enter the exact node IDs in the options:

- `puffer_mitte_oben_node_id`
- `puffer_mitte_unten_node_id`

When set, the integration dynamically creates `puffer_temperatur_mitte_oben` and `puffer_temperatur_mitte_unten` (polled in group 1 like other buffer temps).

### Proper Component Toggling & Entity Sync

Enabling/disabling a component group (HK3, WW2, Netzpumpe 2, ...) automatically enables or disables the corresponding entities via the entity registry. No manual enabling of dozens of entities required.

### Robust Write Handling

All writes go through:
- Debounce (rapid changes collapse to one command)
- Immediate optimistic update in the UI
- HIGH priority in the access queue
- Automatic rollback on failure

---

<br>

## Architecture

```
User / HA UI / Automations
          |
HdgNodeEntity (thin platforms: sensor / number / select)
          |
HdgEntityRegistry (definitions → polling groups + active nodes + writable lookup + component groups)
          |
HdgDataUpdateCoordinator
          |
HdgApiAccessManager (priority queue: HIGH for sets, MEDIUM/LOW for polling)
          |
HdgCommandExecutor
          |
HdgApiClient + HdgApiProtocol (V2 modern or V1 legacy — auto detected)
          |
HDG Boiler Web Interface
```

**Key Design Principles**
- Only poll what is actually enabled.
- User-initiated writes always win.
- Protect the weak boiler controller at all costs (queuing, preemption, backoff, maintenance mode).
- Definition-driven: almost everything is driven from `SENSOR_DEFINITIONS` in `definitions.py`.

---

<br>

## Installation

### Via HACS (Recommended)

1. Open **HACS** → **Integrations**.
2. Search for **"HDG Bavaria Boiler"**.
3. Click **Download**.
4. **Restart Home Assistant**.

### Manual Installation

1. Download the latest release from the [Releases page](https://github.com/banter240/hdg_bavaria_homeassistant/releases).
2. Extract and copy the `custom_components/hdg_boiler` folder into your Home Assistant `config/custom_components/` directory.
3. Restart Home Assistant.

---

<br>

## Configuration

### Initial Setup

Settings → Devices & Services → **Add Integration** → "HDG Bavaria Boiler"

You only need the **Host IP** (static IP recommended) of the boiler.

### Rich Options Flow

The options are organized in collapsible sections:

- **Components** — Toggle which optional hardware you have (HK2–6, WW2, Solar, Puffer 2, Netzpumpen, etc.).
- **Puffer** — Enter node IDs for additional middle buffer temperature sensors.
- **Polling** — Individual intervals for the 5 polling groups.
- **Connection** — Timeouts and fallback ping.
- **Logging** — Log level, advanced logging, source timezone.
- **Advanced** — Preemption timeouts, error thresholds, maintenance mode.

Changes take effect after a reload (the integration does **not** wait for all polls to finish when saving options).

---

<br>

## Entities & Controls

Entities are created from a central definition file. Only nodes belonging to enabled entities are polled.

**Platforms:**
- `sensor` — temperatures, percentages, counters, status, diagnostics
- `number` — writable setpoints and configuration values
- `select` — operating modes and discrete settings

**Component Groups**

All optional components start with their entities disabled. Enable the component in the options and the corresponding entities will be enabled automatically via the registry.

See the Component Support table above.

---

<br>

## Services

### `hdg_boiler.set_node_value`

Raw node write (for power users and advanced automations).

### `hdg_boiler.get_node_value`

Read the current raw value from the integration's cache (debugging).

---

<br>

## Known Constraints

- The boiler's built-in web server is relatively weak — the integration is heavily optimized to avoid overloading it.
- Some advanced parameters are only available on certain firmware versions or boiler models.
- Writable values are validated against the ranges and steps defined in the boiler's data points.

---

<br>

## Troubleshooting

- Enable debug logging:
  ```yaml
  logger:
    logs:
      custom_components.hdg_boiler: debug
  ```
- Download diagnostics from the integration card.
- Use the `get_node_value` service to inspect raw values.
- Check for "preemption", "fallback", or "maintenance" messages in the logs.

---

<br>

## Frequently Asked Questions (FAQ)

**Q: Why are many entities disabled by default?**
A: To keep your Home Assistant clean. Only enable the components (HK2, WW2, Solar, etc.) that you actually have.

**Q: Can I set puffer middle temperatures?**
A: Yes — enter the node IDs in the integration options under the Puffer section. The entities will be created dynamically.

**Q: Does it support my second hot water tank (WW2)?**
A: Yes. Enable `enable_ww2` in the options.

---

<br>

## Documentation

For deeper technical details (architecture, polling strategy, entity definitions, etc.) see the files in `dev/workspace/context/`.

---

<br>

## ☕ Support the Project

This integration is developed entirely in my free time.

If it helps you get better control and visibility of your heating system, a coffee is very much appreciated.

<a href="https://buymeacoffee.com/banter240" target="_blank"><img src="https://cdn.buymeacoffee.com/buttons/v2/default-yellow.png" alt="Buy Me A Coffee" style="height: 50px !important;width: 181px !important;" ></a>

---

## Disclaimer

This is an unofficial integration. Not affiliated with HDG Bavaria GmbH. Use at your own risk.

## License

GNU General Public License v3.0

---

*This README is intentionally practical. For the full technical picture see `dev/workspace/context/`.*
