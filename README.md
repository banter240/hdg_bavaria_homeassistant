# HDG Bavaria Boiler Integration for Home Assistant

[![hacs_badge](https://img.shields.io/badge/HACS-Custom-41BDF5.svg)](https://github.com/hacs/integration)
![GitHub all releases](https://img.shields.io/github/downloads/banter240/hdg_bavaria_homeassistant/total)
![GitHub](https://img.shields.io/github/license/banter240/hdg_bavaria_homeassistant)
![GitHub issues by-label](https://img.shields.io/github/issues/banter240/hdg_bavaria_homeassistant/bug?color=red)
![GitHub contributors](https://img.shields.io/github/contributors/banter240/hdg_bavaria_homeassistant)
[![semantic-release: conventional commits](https://img.shields.io/badge/semantic--release-conventionalcommits-e10079?logo=semantic-release)](https://github.com/semantic-release/semantic-release)

<!-- Optional: Add more badges like community forum, buy me a coffee if you set them up -->

An unofficial Home Assistant integration to monitor and control HDG Bavaria heating systems. This integration communicates with the boiler's web interface to retrieve data and send commands.

---

> 🚧 **Development Status:** This integration is an early release and should be considered in a "beta" stage. While it is actively used and currently runs stable (e.g., on an HDG Euro 50 model without known issues), further development and refinements are ongoing. Your feedback and contributions are highly appreciated!

---

<!-- START doctoc generated TOC please keep comment here to allow auto update -->
<!-- DON'T EDIT THIS SECTION, INSTEAD RE-RUN doctoc TO UPDATE -->

**Table of Contents**

- [About This Integration](#about-this-integration)
- [Features](#features)
- [Prerequisites](#prerequisites)
- [Installation](#installation)
  - [Via HACS (Recommended)](#via-hacs-recommended)
  - [Manual Installation](#manual-installation)
- [Configuration](#configuration)
  - [Initial Setup](#initial-setup)
  - [Integration Options](#integration-options)
- [Supported Entities](#supported-entities)
  - [Sensors](#sensors)
  - [Number Entities (Controls)](#number-entities-controls)
- [Services](#services)
  - [hdg_boiler.set_node_value](#hdg_boilerset_node_value)
  - [hdg_boiler.get_node_value](#hdg_boilerget_node_value)
- [Troubleshooting & Debugging](#troubleshooting--debugging)
- [Contributing](#contributing)
- [Disclaimer](#disclaimer)
- [License](#license)

<!-- END doctoc generated TOC please keep comment here to allow auto update -->

## About This Integration

This custom component allows you to integrate your HDG Bavaria boiler (e.g., HDG Euro, K-Series, Compact, etc., that support the web interface) into Home Assistant. It provides sensor entities to monitor various parameters of your heating system and number entities to control certain settings. The integration dynamically determines which data points to poll based on the defined entities and groups them for efficient fetching. You can configure the polling intervals for these groups to balance data freshness with the load on the boiler's controller.

## Features ✨

- **Sensor Data**: Access a wide range of data points from your boiler, including:
  - Temperatures (boiler, buffer, flue gas, outside, heating circuits, etc.)
  - Status information (boiler state, pump status, operating modes)
  - Operational values (oxygen levels, air flap positions, fan speeds)
  - Counters and statistics (operating hours, energy consumption)
- **Control Capabilities**: Adjust specific boiler settings through Home Assistant:
  - Heating circuit target temperatures (e.g., day/night setpoints) via Number entities.
  - Parallel shift for heating curves via Number entities.
  - Other configurable parameters (depending on your boiler model and `SENSOR_DEFINITIONS`) via Number entities.
- **Robust Write Operations**: A dedicated background worker handles 'set value' API calls, featuring queuing, retry logic with exponential backoff, and specific handling for connection errors.
- **Configurable Polling Groups**: Data is fetched in distinct groups (e.g., Realtime, Status, Config/Counters) with individually configurable scan intervals via the integration options. These groups are dynamically built based on entity definitions.
- **Intelligent Data Parsing**: Handles various data formats, including locale-specific numbers, enumerations, and datetimes, with specific logic for HDG API quirks.
- **API Connection Management**: Includes ICMP ping pre-checks and API response validation to ensure reliable communication and detect boiler online/offline status.
- **Custom Services**: Provides `set_node_value` to directly set values for specific HDG nodes and `get_node_value` to retrieve raw values from the integration's data cache.
- **Device Diagnostics**: Access diagnostic information through Home Assistant to aid in troubleshooting.
- **Dynamic Entity Creation**: Entities are created based on a comprehensive `SENSOR_DEFINITIONS` map in `definitions.py`, which also dictates their polling group assignment.
- **Internationalization**: Supports multiple languages for entity names and states via Home Assistant's translation system.

## Prerequisites

- An HDG Bavaria boiler with a network interface and an accessible web API. Please consult your boiler's manual or HDG service partner to ensure API access is enabled and to understand any implications.
- A **static IP address** assigned to your HDG boiler on your local network. This is crucial for reliable communication.
- Home Assistant version 2024.6.0 or newer (recommended).

## Installation

### Via HACS (Recommended)

1.  **Ensure HACS is installed.** If not, follow the HACS installation guide.
2.  **Add as a custom repository:**
    - Go to HACS in your Home Assistant.
    - Click on "Integrations".
    - Click the three dots in the top right corner and select "Custom repositories".
    - In the "Repository" field, enter the URL of this GitHub repository: `https://github.com/banter240/hdg_bavaria_homeassistant` (replace `banter240` with your actual GitHub username or the correct path if forked).
    - Select "Integration" as the category.
    - Click "Add".
3.  **Install the integration:**
    - Search for "HDG Bavaria Boiler" in HACS.
    - Click on the integration.
    - Click "Download" and follow the prompts.
4.  **Restart Home Assistant.** This is important for the integration to be loaded.

### Manual Installation

1.  Download the latest release from the Releases page
2.  Extract the downloaded archive.
3.  Copy the `custom_components/hdg_boiler` directory into your Home Assistant `config/custom_components/` directory. If `custom_components` doesn't exist, create it.
4.  Restart Home Assistant.

## Configuration

### Initial Setup

After installation (and restarting Home Assistant), the integration can be configured via the UI:

1.  Go to **Settings** -> **Devices & Services** in Home Assistant.
2.  Click the **+ ADD INTEGRATION** button in the bottom right.
3.  Search for "HDG Bavaria Boiler" and select it.
4.  Follow the on-screen instructions:
    - **Host IP Address or Hostname**: Enter the static IP address or hostname of your HDG boiler.
    - **Alias for the Boiler (optional)**: Provide a friendly name for your boiler (e.g., "Euro 50", "Kellerheizung"). This will be used in device and entity naming. If left blank, the IP address will be used.

The integration will attempt to connect to your boiler and perform an initial data fetch. If the boiler is unreachable during setup, Home Assistant will automatically retry later.

### Integration Options

Once the integration is added, you can adjust its settings:

> ℹ️ Changes to these options require a reload of the integration instance to take effect.

1.  Go to **Settings** -> **Devices & Services**.
2.  Find the "HDG Bavaria Boiler" integration card.
3.  Click on **CONFIGURE**.
4.  You can adjust the following:
    - **Scan Intervals**: Modify the polling frequency (in seconds) for different groups of data. These groups are defined internally based on entity types and their typical update frequency.
      - Realtime Core Values
      - General Status Values
      - Config/Counters Part 1, 2, and 3
        Shorter intervals provide more up-to-date data but increase the load on the boiler's controller. Longer intervals are suitable for less frequently changing data. The minimum allowed interval is 15 seconds, and the maximum is 86430 seconds (approx. 24 hours).
    - **Source Timezone**: Specify the timezone configured on your HDG boiler's controller (e.g., `Europe/Berlin`). This is crucial for correctly interpreting datetime values received from the boiler.
    - **Enable Debug Logging**: Activate verbose logging for polling cycles and set value operations, useful for troubleshooting. Be aware that this can generate large log files.

## Supported Entities

Entities are dynamically created based on the `SENSOR_DEFINITIONS` within the integration's `definitions.py` file. The availability of specific entities depends on your boiler model and its configuration.

### Sensors

A variety of sensor entities are created, including:

- **Temperatures**: Outside temperature, boiler temperature, buffer temperatures (top, middle, bottom), flue gas temperature, heating circuit flow/return temperatures, etc. (Typically `device_class: temperature`, unit: `°C` or `K`).
- **Status & Enum Values**: Boiler status (e.g., "Ready", "Heating-up", "Fault"), pump status (On/Off), operating modes, selected fuel type, etc. (Displayed as text).
- **Percentages**: Material quantity, air flap positions, fan speeds, O2 levels, buffer charge state, etc. (Typically `unit_of_measurement: %`).
- **Counters & Durations**: Operating hours, energy consumption (kWh, MWh), maintenance timers, etc. (Various `device_class` like `duration`, `energy`, `state_class: total_increasing`).
- **Pressures**: Negative pressure in the boiler (Typically `device_class: pressure`, unit: `Pa`).
- **Diagnostic Info**: Software versions, MAC address, system labels.

### Number Entities (Controls)

Number entities allow you to view and adjust specific numeric settings on your boiler. These typically correspond to configurable parameters defined as writable in `SENSOR_DEFINITIONS`. Examples include:

- **`number.hdg_boiler_<alias>_tagbetrieb_raumtemperatur_soll`**: Target room temperature for day mode (Heating Circuit 1).
- **`number.hdg_boiler_<alias>_hk1_parallelverschiebung`**: Parallel shift for the heating curve (Heating Circuit 1) in Kelvin.
- **`number.hdg_boiler_<alias>_hk1_steilheit`**: Slope of the heating curve (Heating Circuit 1).
- Other setpoints or configuration values as defined in `SENSOR_DEFINITIONS` with `ha_platform: "number"` and `writable: true`.

These entities will appear under the device for your HDG boiler and can be added to your dashboards.

## Services

This integration provides custom services for more direct interaction with the boiler's nodes.

### `hdg_boiler.set_node_value`

Allows you to set a specific value for a writable HDG node via the background worker.

**Service Data:**

| Field     | Description                                                                                                                                                          | Example  | Required |
| :-------- | :------------------------------------------------------------------------------------------------------------------------------------------------------------------- | :------- | :------- |
| `node_id` | The base ID of the HDG Node to set (e.g., '6022'). Must correspond to an entity defined as a 'number' platform with write access in `SENSOR_DEFINITIONS`.            | `"6022"` | Yes      |
| `value`   | The value to send to the node. It will be validated against the entity's configured type (int, float1, float2), range, and step from its `SENSOR_DEFINITIONS` entry. | `"21.5"` | Yes      |

**Important Notes ⚠**

- Use this service with caution. Setting incorrect values could potentially affect your boiler's operation.
- The `node_id` refers to the base ID (e.g., "6022" for `hk1_soll_normal`). The integration handles any necessary API formatting.
- The service relies on the `SENSOR_DEFINITIONS` for the specified `node_id` to determine if it's writable and to perform validation (min/max value, step, data type for API). **The integration performs strict validation and does not automatically round values that do not match the defined step or type. Ensure the value you provide is appropriate.**

### `hdg_boiler.get_node_value`

> ℹ️ This service is primarily for debugging and advanced use cases.
> Retrieves the current raw string value of a specific node from the integration's internal data cache. This cache is updated by polling the HDG boiler or immediately after a successful `set_node_value` call for the same node.

**Service Data:**

| Field | Description | Example | Required |
| :-------- | :----------------------------------------------------------------aries/hdg_boiler/README.md | :-------- | :------- |
| `node_id` | The base ID of the HDG Node to retrieve (e.g., '22003'). Numeric inputs will be treated as strings by HA. | `"22003"` | Yes |

**Return Value:**

> ℹ️ The response is returned directly to the service caller (e.g., Developer Tools -> Services).
> This service call, when executed via Developer Tools, will show the response in the "Service Call Response" section. The response will contain a `value` key with the raw string value of the node as stored in the coordinator, or `null` if the node is not found in the cache.

Example response:

```json
{
  "node_id": "22003",
  "value": "75.3",
  "status": "found"
}
```

## Troubleshooting & Debugging

If you encounter issues, here are some steps to diagnose the problem:

1.  **Check Boiler Connectivity**: Ensure your HDG boiler is powered on, connected to your network, and has a stable IP address. Verify that the web interface/API is accessible from your network (e.g., by trying to open its IP address in a web browser).
2.  **Verify Configuration**: Double-check the Host IP address in the integration configuration.
3.  **Check Integration Options**: Ensure the scan intervals are appropriate for your network and boiler controller. Verify the Source Timezone is correctly set.
4.  **Enable Debug Logging**:
    - Go to the integration's **Options** (Settings -> Devices & Services -> HDG Bavaria Boiler -> CONFIGURE).
    - Enable "Enable Debug Logging" (this controls more general debug logs).
    - Restart Home Assistant or reload the integration.
5.  **Examine Logs**: Check the Home Assistant logs (Settings -> System -> Logs -> Load Full Logs) for messages related to `custom_components.hdg_boiler`.
6.  **Developer Tools**:
    - **States**: Inspect the state and attributes of your HDG boiler entities (Settings -> Developer Tools -> States). Attributes often contain the raw HDG node ID (`hdg_node_id`) and the raw value (`hdg_raw_value`) received from the API, which can be helpful.
    - **Services**: Use the `hdg_boiler.get_node_value` service to query raw values for specific nodes.
7.  **Diagnostics**:
    - Go to **Settings** -> **Devices & Services**.
    - Find your HDG Boiler device.
    - Click the three dots on the device card and select "Download diagnostics". This file contains redacted configuration and state information that can be helpful for debugging.

> ℹ️ Note: When reporting issues on GitHub, please include relevant log snippets (with debug logging enabled) and the diagnostics file.

## Contributing

Contributions are welcome! If you have ideas for improvements, find bugs, or want to add support for more features/nodes:

- Please open an Issue to discuss your ideas or report bugs.
- If you'd like to contribute code, please submit a Pull Request.
- If you are missing specific sensors for your HDG boiler model, feel free to request them via an Issue or, if you're comfortable, add them to the `SENSOR_DEFINITIONS` in `definitions.py` and submit a Pull Request.

## Disclaimer

This is an unofficial, community-developed integration. It is not affiliated with or endorsed by HDG Bavaria GmbH. Use this integration at your own risk. The developers are not responsible for any damage or malfunction of your heating system that may arise from the use of this software. Always exercise caution when controlling your heating system remotely or automatically.

## License

This project is licensed under the GNU General Public License v3.0. See the LICENSE file for details.

<!-- Replace banter240 in the badge URLs above with your actual GitHub username or the correct path -->
