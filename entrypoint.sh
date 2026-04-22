#!/bin/bash
set -e

# Check if TLauncher.jar exists, if not download it
if [ ! -f /home/app/launcher/TLauncher.jar ]; then
    echo "TLauncher.jar not found, downloading..."

    # Create temp directory for download
    TEMP_DIR=$(mktemp -d)
    cd "$TEMP_DIR"

    # Download and extract TLauncher
    if curl -sL "https://tlauncher.org/jar" -o tlauncher.zip 2>/dev/null; then
        :
    elif wget -q "https://tlauncher.org/jar" -O tlauncher.zip; then
        :
    else
        echo "Error: Neither curl nor wget could download TLauncher. Manually place TLauncher.jar in ./launcher/"
        exit 1
    fi

    # Extract and move to launcher directory
    # Try unzip first; if it fails or contains no JAR, treat download as direct JAR
    if unzip -q tlauncher.zip -d extracted/ 2>/dev/null; then
        JAR=$(find extracted -name "TLauncher.jar" | head -1)
        if [ -n "$JAR" ]; then
            mv "$JAR" /home/app/launcher/TLauncher.jar
        else
            echo "Error: TLauncher.jar not found inside archive"
            exit 1
        fi
    else
        mv tlauncher.zip /home/app/launcher/TLauncher.jar
    fi

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
