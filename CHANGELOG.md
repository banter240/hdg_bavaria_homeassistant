## [0.8.0](https://github.com/banter240/hdg_bavaria_homeassistant/compare/v0.7.4...v0.8.0) (2025-07-04)

### ✨ New Features

* feat(architecture): Introduce robust API access and dynamic polling management

This release marks a significant architectural overhaul, enhancing the integration's stability, reliability, and responsiveness.

Key changes include:

- **Centralized API Access Management**: A new `HdgApiAccessManager` now routes all API requests (for polling and setting values). This manager prioritizes requests (`set_value` calls take precedence over routine polling), handles queuing, performs retries with exponential backoff, and ensures resilient communication with the boiler. It replaces and deprecates the previous `HdgSetValueWorker`, creating a more comprehensive and robust system.

- **Dynamic Polling Group Management**: A new `PollingGroupManager` dynamically builds polling groups from entity definitions in `definitions.py`. This enables more flexible and extensible data fetching, ensuring only relevant data points are polled at configurable intervals.

- **Refactored Data Update Coordinator**: The `HdgDataUpdateCoordinator` has been refactored to utilize the new API and polling managers. This results in improved startup reliability, better handling of connection errors, and dynamic adjustment of polling frequencies.

- **Improved Writable Entity Handling**: `Number` entities now use `setter_type`, `setter_min_val`, `setter_max_val`, and `setter_step` from `SENSOR_DEFINITIONS` for precise validation and control. This ensures values sent to the boiler are always within the expected ranges and formats.

Collectively, these changes deliver a more stable, efficient, and maintainable integration, providing a smoother user experience and a stronger foundation for future development.

## [0.7.4](https://github.com/banter240/hdg_bavaria_homeassistant/compare/v0.7.3...v0.7.4) (2025-06-21)

### 🐛 Bug Fixes

* fix: Set state class for energy sensor definition

Updated the SENSOR_DEFINITIONS entry to set 'ha_state_class' to SensorStateClass.MEASUREMENT instead of None for the relevant energy sensor. This change ensures proper classification and handling of the sensor's state in Home Assistant.

## [0.7.3](https://github.com/banter240/hdg_bavaria_homeassistant/compare/v0.7.2...v0.7.3) (2025-06-21)

### 🐛 Bug Fixes

* fix(hdg_boiler): Reduce excessive INFO logging for unexpected API fields

The HDG boiler API frequently returns 'hidden' and 'background' fields which, while technically
"unexpected" based on the initial explicit field list, are consistently present and do not
indicate a functional issue. The current logging configuration results in a high volume of
INFO level messages for each data refresh, even in debug mode, leading to unnecessary log
spam and obscuring potentially more critical information.

This commit updates the `_async_handle_data_refresh_response` method in `api.py` to
explicitly include 'hidden' and 'background' in the set of expected fields. This change
ensures that the INFO log message "Item has unexpected fields" is only triggered for
truly new or unknown fields returned by the API, significantly reducing log output
without losing valuable information about genuinely unexpected data structures.

The core functionality of processing the API response remains unchanged, as these fields
were already being safely ignored. This is purely a logging refinement to improve system
observability and reduce noise.

## [0.7.2](https://github.com/banter240/hdg_bavaria_homeassistant/compare/v0.7.1...v0.7.2) (2025-06-21)

### 🐛 Bug Fixes

- fix(build): Correct ZIP archive structure for HACS

The previous version of the publish.sh script created a ZIP file containing a parent directory (e.g., hdg_boiler/).

This incorrect structure prevents HACS from correctly installing and loading the integration, as it expects the component's files (manifest.json, etc.) to be at the root of the archive.

This commit modifies the script to change directory into the component's source folder before running the zip command. By zipping the contents ('.') from within that directory, the resulting archive now has the correct flat structure required by HACS.

## [0.7.1](https://github.com/banter240/hdg_bavaria_homeassistant/compare/v0.7.0...v0.7.1) (2025-06-21)

### 🐛 Bug Fixes

- fix(release): Improve release notes format and clean up changelog

## [0.7.0](https://github.com/banter240/hdg_bavaria_homeassistant/compare/v0.6.1...v0.7.0) (2025-06-21)

### ✨ New Features

- **core:** Introduce background worker, dynamic polling, and full CI/CD pipeline ([70259d2](https://github.com/banter240/hdg_bavaria_homeassistant/commit/70259d204f5d5ddf741a4b2a9d1cc992f54005e1))

### 🐛 Bug Fixes

- **ci:** Prevent release workflow loop ([affb6a0](https://github.com/banter240/hdg_bavaria_homeassistant/commit/affb6a0f99e95483512fb7449d4a81b594e930af))
