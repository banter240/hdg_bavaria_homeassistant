#!/bin/bash
# This script creates a HACS-compatible ZIP archive with a static filename.

# --- CUSTOMIZABLE VARIABLES ---
DOMAIN_NAME="hdg_boiler"
RELEASE_NAME="${DOMAIN_NAME}.zip"
DIST_DIR="dist"
# --- END CUSTOMIZABLE VARIABLES ---

# Stop the script immediately if a command fails.
set -e

echo "--------------------------------------------------"
echo "HACS Release Asset Build Script started..."
echo "Domain Name: ${DOMAIN_NAME}"
echo "Release ZIP Name: ${RELEASE_NAME}"
echo "Dist Directory: ${DIST_DIR}"
echo "Current Working Directory: $(pwd)"
echo "--------------------------------------------------"

# Create the dist directory if it doesn't exist.
# The -p flag ensures no errors occur if it already exists.
mkdir -p "${DIST_DIR}"
echo "Ensured that the directory '${DIST_DIR}' exists."

# Path to the source directory of your integration.
SOURCE_DIR="custom_components/${DOMAIN_NAME}"

# Check if the source directory exists.
if [ ! -d "${SOURCE_DIR}" ]; then
  echo "ERROR: The source directory '${SOURCE_DIR}' was not found!"
  echo "Please ensure that DOMAIN_NAME is set correctly and the directory exists."
  exit 1
fi
echo "Source directory '${SOURCE_DIR}' found."

# Create the full path to the target ZIP file.
# The ZIP file will be placed in the DIST_DIR in the main repository directory.
# The script is run from the root of the repo, so ../../ is not necessary
# if cd is done into the SOURCE_DIR. We zip from outside or adjust the path.

# Option 1: Zip from outside the SOURCE_DIR (simpler for paths)
echo "Creating ZIP archive '${DIST_DIR}/${RELEASE_NAME}' from the content of '${SOURCE_DIR}'..."
# zip [options] [archive_name] [what_to_zip] -x [patterns_to_exclude]
# We use -j to junk paths inside the ZIP,
# but for HACS we want to keep the structure *inside* the custom_components/DOMAIN_NAME folder,
# but not the custom_components/DOMAIN_NAME path itself in the ZIP.
# Therefore, it's better to change into the directory and pack from there.

# Option 2: Use pushd to change into the source directory (preferred for HACS)
echo "Changing into directory '${SOURCE_DIR}' using pushd..."
pushd "${SOURCE_DIR}" > /dev/null # Suppress output of pushd


echo "Current working directory after cd: $(pwd)"
echo "Creating ZIP archive '${RELEASE_NAME}' with content of the current directory..."
# The ZIP is created relative to the current directory (i.e., SOURCE_DIR),
# but we want to place it in the DIST_DIR of the project root.
# Therefore, ../../ to go up two levels (out of DOMAIN_NAME and out of custom_components).
zip -r "../../${DIST_DIR}/${RELEASE_NAME}" . \
    -x ".DS_Store" \
    -x "__pycache__/*" \
    -x "*.pyc" \
    -x "node_modules/*" \
    -x ".devcontainer/*" \
    -x ".git/*" \
    -x ".github/*" \
    -x ".pytest_cache/*" \
    -x ".ruff_cache/*" \
    -x ".mypy_cache/*" \
    -x ".vscode/*" \
    -x "tests/*" \
    -x "scripts/*"
    # Add other exclusions here if necessary.
    # Example: -x "local_secrets.yaml"

echo "ZIP archive successfully created: '../../${DIST_DIR}/${RELEASE_NAME}' (relative to $(pwd))"

# Change back to the original directory using popd.
echo "Changing back to the original project directory using popd..."
popd > /dev/null # Suppress output of popd
echo "Current working directory after cd back: $(pwd)"

echo "--------------------------------------------------"
echo "HACS Release Asset Build Script finished."
echo "The file should be located here: '${DIST_DIR}/${RELEASE_NAME}'"
echo "--------------------------------------------------"

# Optional: List the content of the dist directory to verify the result.
echo "Content of the '${DIST_DIR}' directory:"
ls -la "${DIST_DIR}"
