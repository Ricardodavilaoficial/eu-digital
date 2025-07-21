#!/usr/bin/env bash

# Exit immediately if a command exits with a non-zero status.
set -e

# Install ffmpeg directly without updating apt lists
# The '-y' flag automatically answers yes to prompts.
echo "--- Installing ffmpeg ---"
apt install -y ffmpeg

# Run your original build command
echo "--- Running Poetry Install ---"
poetry install --no-root

echo "--- Build process complete ---"
