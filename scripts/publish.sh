#!/bin/bash
#
# ==============================================================================
# Release Asset Publishing Script for HDG Boiler
# ==============================================================================
#
# Description:
#   This script is executed by the semantic-release process to prepare the
#   release assets. It performs the following steps:
#     1. Validates script arguments and required tools (zip, jq).
#     2. Updates the 'version' in manifest.json.
#     3. Creates a versioned, HACS-compatible ZIP archive with the correct
#        internal structure.
#     4. Updates the 'hacs.json' manifest with the new versioned filename.
#
# ==============================================================================

# Exit immediately if a command exits with a non-zero status.
set -e

# --- Color Definitions & Log Functions ---
COLOR_BLUE='\033[1;34m'
COLOR_GREEN='\033[1;32m'
COLOR_YELLOW='\033[1;33m'
COLOR_RED='\033[1;31m'
COLOR_RESET='\033[0m'
log_info() { echo -e "${COLOR_BLUE}INFO: $1${COLOR_RESET}"; }
log_success() { echo -e "${COLOR_GREEN}SUCCESS: $1${COLOR_RESET}"; }
log_warn() { echo -e "${COLOR_YELLOW}WARNING: $1${COLOR_RESET}"; }
log_error() { echo -e "${COLOR_RED}ERROR: $1${COLOR_RESET}" >&2; }

# --- Pre-flight Checks ---
log_info "Running pre-flight checks..."
for tool in zip jq; do
  if ! command -v "$tool" &> /dev/null; then
    log_error "Required tool '$tool' is not installed."
    exit 1
  fi
done
if [ $# -ne 1 ]; then
  log_error "A version number must be provided. Usage: $0 <version>"
  exit 1
fi
log_info "All checks passed."

# --- Configuration Variables ---
readonly NEXT_RELEASE_VERSION="$1"
readonly DOMAIN="hdg_boiler"
readonly DIST_DIR="dist"
readonly ZIP_FILENAME="${DOMAIN}_${NEXT_RELEASE_VERSION}.zip"
readonly SOURCE_DIR="custom_components/${DOMAIN}"
readonly COMPONENT_MANIFEST_PATH="${SOURCE_DIR}/manifest.json"
readonly HACS_MANIFEST_PATH="hacs.json"

log_info "Starting release asset preparation for version ${NEXT_RELEASE_VERSION}..."

# --- Main Execution ---

# 1. Update component manifest.json version
if [ -f "$COMPONENT_MANIFEST_PATH" ]; then
  log_info "Updating version in '${COMPONENT_MANIFEST_PATH}'..."
  jq ".version = \"${NEXT_RELEASE_VERSION}\"" "$COMPONENT_MANIFEST_PATH" > "${COMPONENT_MANIFEST_PATH}.tmp" && mv "${COMPONENT_MANIFEST_PATH}.tmp" "$COMPONENT_MANIFEST_PATH"
  log_success "'${COMPONENT_MANIFEST_PATH}' updated to version ${NEXT_RELEASE_VERSION}."
else
  log_warn "'${COMPONENT_MANIFEST_PATH}' not found. Cannot update version."
fi

# 2. Create the distribution directory
log_info "Ensuring distribution directory '${DIST_DIR}' exists..."
mkdir -p "${DIST_DIR}"

# 3. Create the ZIP archive with the correct internal structure for HACS
log_info "Creating ZIP archive at '${DIST_DIR}/${ZIP_FILENAME}'..."
# Change directory INTO the component's source folder
cd "${SOURCE_DIR}"
# Zip the CONTENTS of the current directory ('.') into the dist folder, which is now two levels up.
zip -r "../../${DIST_DIR}/${ZIP_FILENAME}" . -x "*/__pycache__/*" "*.pyc" ".DS_Store"
# Go back to the original root directory
cd ../..
log_success "ZIP archive with correct HACS structure created successfully."


# 4. Update hacs.json
if [ -f "$HACS_MANIFEST_PATH" ]; then
  log_info "Updating filename in '${HACS_MANIFEST_PATH}'..."
  jq ".filename = \"${ZIP_FILENAME}\"" "$HACS_MANIFEST_PATH" > temp.json && mv temp.json "$HACS_MANIFEST_PATH"
  log_success "'${HACS_MANIFEST_PATH}' updated."
else
  log_warn "'${HACS_MANIFEST_PATH}' not found. Skipping update."
fi

# --- DIAGNOSTIC STEP ---
log_info "Running 'git status' to check for modified files before exiting script..."
git status
log_info "--- End of git status ---"

echo
log_success "Release asset preparation complete for version ${NEXT_RELEASE_VERSION}."
