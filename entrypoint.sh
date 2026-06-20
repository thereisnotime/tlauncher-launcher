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

# ── JVM / rendering tuning ────────────────────────────────────────────────────
# Every knob below is controlled by an environment variable with a sane default.
# Defaults are set per display server in the compose overlays (see
# compose.x11.yaml / compose.wayland.yaml); the base file passes any host-set
# value straight through, so you can override any of them on the command line,
# e.g.  JAVAFX_PRISM=sw ./minecraft.py start
#
#   JAVA_UI_SCALE     Swing UI scale factor (1 = off). TLauncher mostly ignores
#                     this, so it stays off unless you force it.
#   JAVA2D_PIPELINE   Swing/Java2D pipeline: default | xrender | opengl | x11
#   JAVAFX_PRISM      JavaFX (news/browser) pipeline: default(hardware) | sw | es2
#   JAVA_DISABLE_GRAB Stop AWT grabbing the X server for popups (true/false)
#   JAVA_PREFER_IPV4  Avoid IPv6 connection stalls in the container (true/false)
#
# These are exported via JAVA_TOOL_OPTIONS (not the command line) because
# TLauncher is a two-stage launcher: the jar we start is only the "starter",
# which spawns a SECOND JVM for the real UI. JAVA_TOOL_OPTIONS is an environment
# variable that every JVM (starter, UI, and the game) inherits.
JAVA_OPTS=()

if [ "${JAVA_DISABLE_GRAB:-true}" = "true" ]; then
    JAVA_OPTS+=("-Dsun.awt.disablegrab=true")
fi

if [ "${JAVA_PREFER_IPV4:-true}" = "true" ]; then
    JAVA_OPTS+=("-Djava.net.preferIPv4Stack=true")
fi

if [ -n "${JAVA_UI_SCALE:-}" ] && [ "${JAVA_UI_SCALE}" != "1" ] && [ "${JAVA_UI_SCALE}" != "1.0" ]; then
    echo "UI scale: ${JAVA_UI_SCALE}"
    JAVA_OPTS+=("-Dsun.java2d.uiScale=${JAVA_UI_SCALE}")
fi

case "${JAVA2D_PIPELINE:-xrender}" in
    opengl) echo "Java2D pipeline: OpenGL"; JAVA_OPTS+=("-Dsun.java2d.opengl=true") ;;
    xrender) echo "Java2D pipeline: XRender"; JAVA_OPTS+=("-Dsun.java2d.xrender=true") ;;
    x11) echo "Java2D pipeline: X11 (unaccelerated)" ;;
    *) echo "Java2D pipeline: JVM default" ;;
esac

case "${JAVAFX_PRISM:-default}" in
    default|"") echo "JavaFX pipeline: default (hardware)" ;;
    *) echo "JavaFX pipeline: ${JAVAFX_PRISM}"; JAVA_OPTS+=("-Dprism.order=${JAVAFX_PRISM}") ;;
esac

# Make JavaFX's GTK use XWayland (X11) rather than trying native Wayland.
export GDK_BACKEND=x11

# Export so the options reach the starter AND the spawned UI JVM (and the game).
export JAVA_TOOL_OPTIONS="${JAVA_OPTS[*]}"
echo "JAVA_TOOL_OPTIONS=${JAVA_TOOL_OPTIONS}"

# Start TLauncher and wait for all child processes
java -jar /home/app/launcher/TLauncher.jar &
JAVA_PID=$!

# Wait for the starter to finish
wait $JAVA_PID

# Keep container alive by waiting for any remaining Java processes
while pgrep -u $(id -u) java > /dev/null; do
    sleep 2
done
