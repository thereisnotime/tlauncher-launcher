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

JAVA_OPTS=()

# Scale the TLauncher Swing GUI on HiDPI/QHD displays. Swing does not auto-scale,
# so we pass the host-detected factor via -Dsun.java2d.uiScale. 1 means no scaling.
if [ -n "${JAVA_UI_SCALE:-}" ] && [ "${JAVA_UI_SCALE}" != "1" ] && [ "${JAVA_UI_SCALE}" != "1.0" ]; then
    echo "Applying UI scale: ${JAVA_UI_SCALE}"
    JAVA_OPTS+=("-Dsun.java2d.uiScale=${JAVA_UI_SCALE}")
fi

# Accelerate the launcher's Swing UI. The default X11 pipeline is unaccelerated
# and stutters (especially opening dropdowns) over XWayland. XRender offloads
# blits/gradients to the X server; OpenGL uses the GPU (set JAVA2D_OPENGL=1).
# JAVA2D_PIPELINE can override entirely (e.g. "x11" to disable acceleration).
case "${JAVA2D_PIPELINE:-${JAVA2D_OPENGL:+opengl}}" in
    opengl|1)
        echo "Java2D pipeline: OpenGL"
        JAVA_OPTS+=("-Dsun.java2d.opengl=true")
        ;;
    x11)
        echo "Java2D pipeline: X11 (unaccelerated)"
        ;;
    *)
        echo "Java2D pipeline: XRender"
        JAVA_OPTS+=("-Dsun.java2d.xrender=true")
        ;;
esac

# Start TLauncher and wait for all child processes
java "${JAVA_OPTS[@]}" -jar /home/app/launcher/TLauncher.jar &
JAVA_PID=$!

# Wait for the starter to finish
wait $JAVA_PID

# Keep container alive by waiting for any remaining Java processes
while pgrep -u $(id -u) java > /dev/null; do
    sleep 2
done
