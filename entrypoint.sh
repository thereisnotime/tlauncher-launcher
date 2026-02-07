#!/bin/bash
set -e

# Check if TLauncher.jar exists, if not download it
if [ ! -f /home/app/launcher/TLauncher.jar ]; then
    echo "TLauncher.jar not found, downloading..."

    # Create temp directory for download
    TEMP_DIR=$(mktemp -d)
    cd "$TEMP_DIR"

    # Download and extract TLauncher
    if command -v curl > /dev/null; then
        curl -sL "https://tlauncher.org/jar" -o tlauncher.zip
    elif command -v wget > /dev/null; then
        wget -q "https://tlauncher.org/jar" -O tlauncher.zip
    else
        echo "Error: Neither curl nor wget found. Please install one or manually place TLauncher.jar in ./launcher/"
        exit 1
    fi

    # Extract and move to launcher directory
    unzip -q tlauncher.zip
    mv TLauncher.v*/TLauncher.jar /home/app/launcher/TLauncher.jar

    # Cleanup
    cd /home/app
    rm -rf "$TEMP_DIR"

    echo "TLauncher.jar downloaded successfully!"
fi

# Start TLauncher and wait for all child processes
java -jar /home/app/launcher/TLauncher.jar &
JAVA_PID=$!

# Wait for the starter to finish
wait $JAVA_PID

# Keep container alive by waiting for any remaining Java processes
while pgrep -u $(id -u) java > /dev/null; do
    sleep 2
done
