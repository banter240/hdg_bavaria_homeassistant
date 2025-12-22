## [0.13.0-dev.1](https://github.com/banter240/hdg_bavaria_homeassistant/compare/v0.12.0...v0.13.0-dev.1) (2025-12-22)

### ✨ New Features

* feat(entities): add support for HK2, WW1, Buffer 2 and pellet sensors

- Add comprehensive sensor and control support for Heating Circuit 2 (HK2), Domestic Hot Water 1 (WW1), Buffer 2, and pellet storage monitoring.
- Introduce 'create_mass_sensor' factory for weight-based data points.
- Implement 'entity_registry_enabled_default' logic to keep advanced entities disabled by default, ensuring a clean UI for new users.
- Add full translations (DE/EN) for all new entities and rename 'Betriebsart' to 'HK1 Betriebsart' for clarity.
- Major refactor of 'definitions.py': factory functions now use explicit, type-safe parameters instead of generic **kwargs, and redundant wrappers have been removed in favor of a centralized 'create_disabled' logic.
- Enhance 'entity.py' with safe attribute propagation and guards to ensure compatibility with various Home Assistant versions.
- Implement a compatibility shim for 'UnitOfMass.TONNES' in 'const.py' to support older Home Assistant environments.
- Reorganize global constants and improve internal documentation/docstrings for better maintainability.
- Fix list formatting and content in 'README.md' and update release documentation.
- Update CI/CD workflow to enable automated semantic releases from the 'dev' branch.
- Address all Sourcery code quality, architecture, and performance review suggestions.

## [0.12.0](https://github.com/banter240/hdg_bavaria_homeassistant/compare/v0.11.0...v0.12.0) (2025-09-18)

### ✨ New Features

* feat(boiler): add smart recovery with fallback ping and improve stability

- add configurable fallback ping interval to periodically check boiler availability when offline
- trigger immediate refresh on successful ping response for faster recovery
- clamp ping delay between min and max limits to avoid zero/negative delays
- revert to fixed interval ping logic for predictable recovery and disable ping if interval set to 0
- refactor ping unsubscribe logic into helper method to reduce duplication
- refactor fallback ping to use async_track_time_interval for cleaner, more robust scheduling
- fix rounding logic in number.py using "round half up" method (math.floor(value + 0.5))
- fix unload bug by calling correct cleanup function in API access manager
- refactor const.py with cleaner organization of ping constants and added comments
- update .gitleaks.toml rules to correctly allowlist the ping unsubscribe variable
- update readme with ICMP ping prerequisites and fallback ping config options with translations

## [0.11.0](https://github.com/banter240/hdg_bavaria_homeassistant/compare/v0.10.0...v0.11.0) (2025-08-22)

### ✨ New Features

* feat(logging): Add configurable log level for preemption errors and fix number entities

This commit introduces a new feature to control the logging of API preemption errors and fixes issues with number entities.

- **Feature**: A new option `log_level_threshold_for_preemption_errors` allows users to define how many consecutive preemption errors must occur before the log level is escalated from INFO to WARNING. This helps in reducing log noise from expected preemptions during normal operation.
- **Fix**: The handling of `number` entities has been improved to correctly parse integer values and to make optimistic updates more reliable. This prevents values from being displayed as floats when they should be integers and ensures the UI reflects the user's intent immediately.

## [0.10.0](https://github.com/banter240/hdg_bavaria_homeassistant/compare/v0.9.0...v0.10.0) (2025-08-14)

### ✨ New Features

* feat(core): add connection error threshold and refactor error handling

This commit introduces a new configuration option, `error_threshold`, to control the number of consecutive connection errors before the integration enters a failure state.

It also includes a major refactoring of the error handling logic in the `HdgDataUpdateCoordinator`:

- Re-introduces the `_update_polling_status` function to simplify error handling and improve readability.
- The `_handle_update_failure` function now distinguishes between connection and polling failures.
- The `_async_update_data` function is updated to use the new error handling mechanism.

Additionally, this commit includes the following changes:

- The `betriebsart` select entity no longer includes the "urlaub" (holiday) option.
- Removes deprecated code from the config flow.
- Adds and updates translations for the new and modified options.
- Updates the `README.md` to document the new `error_threshold` option.

## [0.9.0](https://github.com/banter240/hdg_bavaria_homeassistant/compare/v0.8.0...v0.9.0) (2025-08-12)

### ✨ New Features

* feat(architecture): major architectural refactor and intelligent debouncing

Introduce HdgEntityRegistry to centralize entity and polling group definitions, replacing polling_manager



Overhaul HdgDataUpdateCoordinator with cleaner state management using typed dictionaries (PollingState, SetterState) and robust error handling



Restructure definitions.py with factory functions (e.g., create_temp_sensor) for streamlined sensor and number entity creation, reducing boilerplate and enhancing readability



Move logic into dedicated helper modules for parsing, validation, and API access



Add support for select entities to control operational modes



Implement concurrent polling in HdgDataUpdateCoordinator (coordinator.py) for faster data refresh and reduced update times



Add intelligent debouncing for writable entities (number, select), grouping rapid value changes to prevent API overload and unnecessary calls if final value matches initial state



Enhance debouncing with optimistic state updates and generation tracking to ensure UI responsiveness and prevent stale API requests



Refactor config_flow.py for clarity, separating initial setup (HdgBoilerConfigFlow) and options management (HdgBoilerOptionsFlowHandler)



Improve api.py client with clearer, more robust error handling and concise methods for boiler API interactions



Fix potential race conditions in command handling for reliable operation



Ensure consistent and reliable startup and data fetching



Update README to reflect new architecture and features

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
