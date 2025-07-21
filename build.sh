#!/usr/bin/env bash

# Exit immediately if a command exits with a non-zero status.
set -e

# Update apt-get and install ffmpeg
echo "--- Installing ffmpeg ---"
apt-get update -y
apt-get install -y ffmpeg

# Run your original build command
echo "--- Running Poetry Install ---"
poetry install --no-root

echo "--- Build process complete ---"
