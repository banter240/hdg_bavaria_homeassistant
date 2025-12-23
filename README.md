# HDG Bavaria Boiler Integration for Home Assistant

[![semantic-release: conventional commits](https://img.shields.io/badge/semantic--release-conventionalcommits-e10079?logo=semantic-release)](https://github.com/semantic-release/semantic-release)
[![GitHub release (latest by date)](https://img.shields.io/github/v/release/banter240/hdg_bavaria_homeassistant)](https://github.com/banter240/hdg_bavaria_homeassistant/releases/latest)
[![hacs_badge](https://img.shields.io/badge/HACS-Custom-41BDF5.svg)](https://github.com/hacs/integration)
![GitHub all releases](https://img.shields.io/github/downloads/banter240/hdg_bavaria_homeassistant/total)
![GitHub](https://img.shields.io/github/license/banter240/hdg_bavaria_homeassistant)
![GitHub issues by-label](https://img.shields.io/github/issues/banter240/hdg_bavaria_homeassistant/bug?color=red)
![GitHub contributors](https://img.shields.io/github/contributors/banter240/hdg_bavaria_homeassistant)

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
  - [Select Entities (Controls)](#select-entities-controls)
- [Services](#services)
  - [hdg_boiler.set_node_value](#hdg_boilerset_node_value)
  - [hdg_boiler.get_node_value](#hdg_boilerget_node_value)
- [Troubleshooting & Debugging](#troubleshooting--debugging)
- [Contributing](#contributing)
- [Disclaimer](#disclaimer)
- [License](#license)

<!-- END doctoc generated TOC please keep comment here to allow auto update -->

## About This Integration

This custom component allows you to integrate your HDG Bavaria boiler (e.g., HDG Euro, K-Series, Compact, etc., that support the web interface) into Home Assistant. It provides sensor entities to monitor various parameters of your heating system, number entities to control certain settings, and select entities for managing operational modes. The integration dynamically determines which data points to poll based on the defined entities and groups them for efficient fetching. You can configure the polling intervals for these groups to balance data freshness with the load on the boiler's controller.

## Features

- **Enhanced Stability & Reliability**:
  - **Centralized API Access Management**: All API requests (polling and setting values) are now routed through a dedicated `HdgApiAccessManager`. This manager prioritizes requests (e.g., `set_value` calls take precedence over routine polling), handles queuing, retries with exponential backoff, and ensures robust communication with the boiler. This replaces the previous `set_value` worker with a more comprehensive and resilient system.
  - **Intelligent Command Debouncing**: To protect the boiler from excessive commands, all value-setting requests are debounced. If a value is changed back and forth rapidly (e.g., by a user dragging a slider or quick UI clicks), the integration waits for the changes to settle. It then compares the *final* desired value with the value that existed *before* the changes started. A command is only sent to the boiler if the state has actually changed, preventing unnecessary API calls.
  - **Robust Startup**: Critical fixes ensure Home Assistant starts reliably without timeouts, even with background API tasks.
  - **Accurate Device Information**: `config_url` and other device details are now consistently determined, eliminating previous warnings.
  - **Smart Recovery**: When the boiler goes offline, the integration enters a low-power fallback mode. It will then periodically ping the device and, upon successful response, immediately trigger a full refresh to bring the system back online faster.
- **Dynamic Polling Group Management**: Data is fetched in distinct groups (e.g., Realtime, Status, Config/Counters) with individually configurable scan intervals via the integration options. These groups are dynamically built based on entity definitions, making the integration more flexible and extensible.
- **Intelligent Data Parsing**: Handles various data formats, including locale-specific numbers, enumerations, and datetimes, with specific logic for HDG API quirks.
- **API Connection Management**: Includes ICMP ping pre-checks and API response validation to ensure reliable communication and detect boiler online/offline status.
- **Custom Services**: Provides `set_node_value` to directly set values for specific HDG nodes and `get_node_value` to retrieve raw values from the integration's data cache.
- **Dynamic Entity Creation**: Entities are created based on a comprehensive `SENSOR_DEFINITIONS` map in `definitions.py`, which also dictates their polling group assignment. This ensures that only relevant entities for your boiler model are exposed.
- **Internationalization**: Supports multiple languages for entity names and states via Home Assistant's translation system.
- **Comprehensive Sensor Data**: Access a wide range of data points from your boiler, including:
  - Temperatures (boiler, buffer, flue gas, outside, heating circuits, etc.).
  - Status information (boiler state, pump status, operating modes).
  - Operational values (oxygen levels, air flap positions, fan speeds).
  - Counters and statistics (operating hours, energy consumption).
  - **New:** Support for Heating Circuit 2 (HK2), Domestic Hot Water 1 (WW1), Buffer 2 and pellet storage sensors (Note: These additional entities are disabled by default and must be enabled in Home Assistant).
- **Control Capabilities**: Adjust specific boiler settings through Home Assistant:
  - Heating circuit target temperatures (e.g., day/night setpoints) via Number entities.
  - Parallel shift for heating curves via Number entities.
  - Other configurable parameters (depending on your boiler model and `SENSOR_DEFINITIONS`) via Number entities.
  - Operational modes (e.g., Normal, Party, Summer) via Select entities.
- **Improved Writable Entity Handling**: Number and Select entities now leverage `setter_type`, `setter_min_val`, `setter_max_val`, and `setter_step` (for numbers) and `options` (for selects) from `SENSOR_DEFINITIONS` for precise validation and control, ensuring values sent to the boiler are always within expected ranges and formats.

## Prerequisites

- An HDG Bavaria boiler with a network interface and an accessible web API. Please consult your boiler's manual or HDG service partner to ensure API access is enabled and to understand any implications.
- A **static IP address** assigned to your HDG boiler on your local network. This is crucial for reliable communication.
- Home Assistant version 2024.6.0 or newer (recommended).

## Installation

### Via HACS (Official Store)

The easiest way to install this integration is via HACS (Home Assistant Community Store), where it is available in the default repository.

1.  Open **HACS** in Home Assistant.
2.  Click on **Integrations**.
3.  Click the **Explore & Download Repositories** button (usually a blue button or a generic search bar depending on your HACS version).
4.  Search for **"HDG Bavaria Boiler"**.
5.  Select the integration card and click **Download**.
6.  **Restart Home Assistant** to load the new component.

### Manual Installation

1.  Download the latest `hdg_boiler_*.zip` from the [Releases page](https://github.com/banter240/hdg_bavaria_homeassistant/releases).
2.  Extract the archive.
3.  Copy the `custom_components/hdg_boiler` folder to your Home Assistant `config/custom_components/` directory.
4.  Restart Home Assistant.

## Configuration

### Initial Setup

After installation (and restarting Home Assistant), the integration can be configured via the UI:

1.  Go to **Settings** -> **Devices & Services** in Home Assistant.
2.  Click the **+ ADD INTEGRATION** button in the bottom right.
3.  Search for "HDG Bavaria Boiler" and select it.
4.  Follow the on-screen instructions:
    - **Host IP Address or Hostname**: Enter the static IP address or hostname of your HDG boiler.
    - **Alias for the Boiler (optional)**: Provide a friendly name for your boiler (e.g., "Euro 50", "Kellerheizung"). This will be used in device and entity naming. **Note: This alias cannot be changed after initial setup via the UI.**

The integration will attempt to connect to your boiler and perform an initial data fetch. If the boiler is unreachable during setup, Home Assistant will automatically retry later.

### Integration Options

Once the integration is added, you can adjust its settings:

> ℹ️ Changes to these options require a reload of the integration instance to take effect.

1.  Go to **Settings** -> **Devices & Services**.
2.  Find the "HDG Bavaria Boiler" integration card.
3.  Click on **CONFIGURE**.
4.  You can adjust the following:
    ### Configurable Options

Once the integration is added, you can adjust its settings via **Settings** -> **Devices & Services** -> **HDG Bavaria Boiler** -> **CONFIGURE**.

| Option                                                                                | Description                                                                                                                                                                                                                                                                                                                               | Type     | Default         | Range/Options               |
| ------------------------------------------------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | -------- | --------------- | --------------------------- |
| **Device Alias** (`device_alias`)                                                     | An optional, user-friendly name for this boiler in Home Assistant. If left empty, a default name will be used.                                                                                                                                                                                                                            | Text     | Empty string    | Any text                    |
| **Scan Interval: Realtime Core Values** (`scan_interval_group_1_realtime_core`)       | The interval (in seconds) for polling the most important real-time data from the boiler (e.g., temperatures, operating status).                                                                                                                                                                                                           | Number   | 15              | 15-86430 seconds            |
| **Scan Interval: General Status Values** (`scan_interval_group_2_status_general`)     | The interval (in seconds) for polling general status information from the boiler.                                                                                                                                                                                                                                                         | Number   | 304             | 15-86430 seconds            |
| **Scan Interval: Config/Counters Part 1** (`scan_interval_group_3_config_counters_1`) | The interval (in seconds) for polling configuration and counter data from the boiler (Group 1). This data changes less frequently.                                                                                                                                                                                                        | Number   | 86410           | 15-86430 seconds            |
| **Scan Interval: Config/Counters Part 2** (`scan_interval_group_4_config_counters_2`) | The interval (in seconds) for polling configuration and counter data from the boiler (Group 2).                                                                                                                                                                                                                                           | Number   | 86420           | 15-86430 seconds            |
| **Scan Interval: Config/Counters Part 3** (`scan_interval_group_5_config_counters_3`) | The interval (in seconds) for polling configuration and counter data from the boiler (Group 3).                                                                                                                                                                                                                                           | Number   | 86430           | 15-86430 seconds            |
| **Logging Level** (`log_level`)                                                       | Sets the verbosity of logs for this integration. 'DEBUG' is very verbose and useful for troubleshooting. 'INFO' is the standard for normal operation.                                                                                                                                                                                     | Dropdown | INFO            | DEBUG, INFO, WARNING, ERROR |
| **Enable Advanced Logging** (`advanced_logging`)                                      | Enables additional `INFO`-level logs for important actions (e.g., setting values, API request/response summaries), even when the main integration log level is set to `INFO`. Useful for tracking key operations without enabling full `DEBUG` logging, which can be very verbose.                                                        | Toggle   | False           | True/False                  |
| **Source Timezone** (`source_timezone`)                                               | The timezone in which the boiler provides its time data (e.g., 'Europe/Berlin'). This is important for correct interpretation of date/time values from the boiler.                                                                                                                                                                        | Text     | `Europe/Berlin` | IANA Timezone string        |
| **API Timeout** (`api_timeout`)                                                       | The maximum time (in seconds) to wait for a response from the boiler for any API request. A higher value can help with unstable networks but may lead to longer waits.                                                                                                                                                                    | Number   | 15              | 5-120 seconds               |
| **Connect Timeout** (`connect_timeout`)                                               | The timeout in seconds for establishing the TCP connection.                                                                                                                                                                                                                                                                               | Number   | 5.0             | 3.0-20.0 seconds            |
| **Polling Preemption Timeout** (`polling_preemption_timeout`)                         | The maximum time (in seconds) a low-priority polling request is allowed to run if a higher-priority request (e.g., a setting change) is queued. A lower value ensures faster response to setting changes but may lead to more frequent interruptions with slow boiler responses.                                                          | Number   | 5.0             | 1.0-20.0 seconds            |
| **Connection Error Threshold** (`log_level_threshold_for_connection_errors`)          | The number of consecutive connection failures after which the logging level for connection errors escalates. For example, if set to `5`, the first 4 connection errors will be logged as `INFO`, and the 5th and subsequent errors will be logged as `ERROR`. Non-connection API errors will be logged as `WARNING` after this threshold. | Number   | 5               | 1-60                        |
| **Preemption Error Threshold** (`log_level_threshold_for_preemption_errors`)        | The number of consecutive preemption errors before logging escalates. Below this, errors are logged as `INFO`. At or above, they are logged as `WARNING`.                                                                                                                                                                                          | Number   | 3               | 1-10                        |
| **Error Threshold** (`error_threshold`)                                               | The number of consecutive errors before the integration raises an `UpdateFailed` error and stops trying to reconnect for a while.                                                                                                                                                                                             | Number   | 3               | 1-20                        |
| **Fallback Ping Interval** (`fallback_ping_interval`)                               | The interval (in seconds) to ping the host when it is considered offline. A successful ping will trigger an immediate refresh attempt. Set to `0` to disable. **Note:** This feature requires a working `ping` command on your Home Assistant system. For HAOS/Supervised, this is included. For Container/Core installs, you may need to install `iputils-ping`. | Number   | 30              | 5-300 seconds               |
| **Maintenance Mode** (`maintenance_mode`)                                             | When enabled, the integration will suppress all communication with the boiler (no polling, no set commands). This is intended for maintenance work on the boiler to ensure the safety of service personnel. Entities will appear as 'unavailable'. | Toggle   | False           | True/False                  |

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

- **`number.hdg_boiler_<alias>_hc1_daytime_room_temperature_target`**: Target room temperature for day mode (Heating Circuit 1).
- **`number.hdg_boiler_<alias>_hc1_parallel_shift`**: Parallel shift for the heating curve (Heating Circuit 1) in Kelvin.
- **`number.hdg_boiler_<alias>_hc1_heating_curve_slope`**: Slope of the heating curve (Heating Circuit 1).
- Other setpoints or configuration values as defined in `SENSOR_DEFINITIONS` with `ha_platform: "number"` and `writable: true`.

These entities will appear under the device for your HDG boiler and can be added to your dashboards.

### Select Entities (Controls)

Select entities allow you to choose from a predefined list of options, typically used for operational modes or settings with discrete choices. Examples include:

- **`select.hdg_boiler_<alias>_hc1_operating_mode`**: Main operational mode of the boiler (e.g., Normal, Party, Summer).
- Other configurable options as defined in `SENSOR_DEFINITIONS` with `ha_platform: "select"` and `writable: true`.

## Enabling Additional Entities (HK2, Pellets, etc.)

To keep your Home Assistant instance clean, advanced entities for additional heating circuits (HK2), the second buffer (Buffer 2), or pellet storage monitoring are **disabled by default**.

If your system includes these components, you can easily enable them:
1.  Go to **Settings** -> **Devices & Services**.
2.  Click on the **HDG Bavaria Boiler** integration.
3.  Click on **Entities**.
4.  Filter for "disabled" entities or search for `hk2`, `ww1`, `puffer_2` or `lager`.
5.  Select the desired entities and click **ENABLE SELECTED**.
6.  Wait a few seconds for Home Assistant to start polling these new data points.

## Services

This integration provides custom services for more direct interaction with the boiler's nodes.

### `hdg_boiler.set_node_value`

Allows you to set a specific value for a writable HDG node via the background worker.

**Service Data:**

| Field     | Description                                                                                                                                                                    | Example  | Required |
| :-------- | :----------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | :------- | :------- |
| `node_id` | The base ID of the HDG Node to set (e.g., '6022'). Must correspond to an entity defined as a 'number' or 'select' platform with write access in `SENSOR_DEFINITIONS`.          | `"6022"` | Yes      |
| `value`   | The value to send to the node. It will be validated against the entity's configured type (int, float1, float2, enum key), range, and step from its `SENSOR_DEFINITIONS` entry. | `"21.0"` | Yes      |

**Important Notes ⚠**

- Use this service with caution. Setting incorrect values could potentially affect your boiler's operation.
- The `node_id` refers to the base ID (e.g., "6022" for `hk1_soll_normal`). The integration handles any necessary API formatting.
- The service relies on the `SENSOR_DEFINITIONS` for the specified `node_id` to determine if it's writable and to perform validation (min/max value, step, data type for API). **The integration performs strict validation and does not automatically round values that do not match the defined step or type. Ensure the value you provide is appropriate.**

### `hdg_boiler.get_node_value`

> ℹ️ This service is primarily for debugging and advanced use cases.
> Retrieves the current raw string value of a specific node from the integration's internal data cache. This cache is updated by polling the HDG boiler or immediately after a successful `set_node_value` call for the same node.

**Service Data:**

| Field     | Description                                                                                               | Example   | Required |
| :-------- | :-------------------------------------------------------------------------------------------------------- | :-------- | :------- |
| `node_id` | The base ID of the HDG Node to retrieve (e.g., '22003'). Numeric inputs will be treated as strings by HA. | `"22003"` | Yes      |

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

To get the human-readable value and its unit, you should inspect the corresponding sensor entity in Home Assistant's Developer Tools -> States. For example, for `node_id: "22003"` (Boiler Temperature Actual), you would look at `sensor.hdg_boiler_<alias>_kesseltemperatur_ist`.

## Troubleshooting & Debugging

If you encounter issues, here are some steps to diagnose the problem:

1.  **Check Boiler Connectivity**: Ensure your HDG boiler is powered on, connected to your network, and has a stable IP address. Verify that the web interface/API is accessible from your network (e.g., by trying to open its IP address in a web browser).
2.  **Verify Configuration**: Double-check the Host IP address in the integration configuration.
3.  **Check Integration Options**: Ensure the scan intervals are appropriate for your network and boiler controller. Verify the Source Timezone is correctly set.
4.  **Enable Debug Logging**:

    - To enable full `DEBUG` logging for the integration, add the following to your `configuration.yaml`:

      ```yaml
      logger:
        default: info
        logs:
          custom_components.hdg_boiler: debug
      ```

    - Alternatively, you can change the `Logging Level` option in the integration's configuration to `DEBUG`.
    - Restart Home Assistant or reload the integration after changing logging settings.

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
