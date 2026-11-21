#!/bin/bash
set -e

# A zip/jar starts with "PK". Anything else (an HTML error page, a Cloudflare
# challenge, a truncated download) must never be kept as TLauncher.jar, or every
# later start fails until someone deletes it by hand.
is_zip() { [ -s "$1" ] && [ "$(head -c 2 "$1")" = "PK" ]; }

JAR_PATH=/home/app/launcher/TLauncher.jar
if [ -f "$JAR_PATH" ] && ! is_zip "$JAR_PATH"; then
    echo "TLauncher.jar is not a valid jar (broken earlier download?), fetching it again..."
    rm -f "$JAR_PATH"
fi

if [ ! -f "$JAR_PATH" ]; then
    echo "TLauncher.jar not found, downloading..."
    TEMP_DIR=$(mktemp -d)
    cd "$TEMP_DIR"

    # -f: fail on HTTP errors instead of saving the error page.
    if ! curl -fsSL --retry 3 --connect-timeout 20 "https://tlauncher.org/jar" -o tlauncher.zip \
        && ! wget -q --tries=3 "https://tlauncher.org/jar" -O tlauncher.zip; then
        echo "Error: could not download TLauncher. Manually place TLauncher.jar in ./launcher/"
        exit 1
    fi
    if ! is_zip tlauncher.zip; then
        echo "Error: tlauncher.org returned something that is not a zip/jar (blocked or changed?)."
        echo "Download TLauncher manually and place TLauncher.jar in ./launcher/"
        exit 1
    fi

    # The download is either a zip that contains TLauncher.jar, or the jar itself.
    JAR=""
    if unzip -q tlauncher.zip -d extracted/ 2>/dev/null; then
        JAR=$(find extracted -name "TLauncher*.jar" | head -1)
    fi
    if [ -n "$JAR" ]; then
        mv "$JAR" "$JAR_PATH.tmp"
    else
        mv tlauncher.zip "$JAR_PATH.tmp"
    fi
    if ! is_zip "$JAR_PATH.tmp"; then
        rm -f "$JAR_PATH.tmp"
        echo "Error: extracted TLauncher.jar is not a valid jar"
        exit 1
    fi
    mv "$JAR_PATH.tmp" "$JAR_PATH"

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
