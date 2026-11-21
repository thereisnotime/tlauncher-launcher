"""Optional system tray support and the single-instance socket.

The tray icon itself uses pystray (optional dependency). On KDE Plasma, and on
GNOME with the AppIndicator extension (Ubuntu ships it on), pystray talks the
StatusNotifierItem D-Bus protocol through its appindicator backend. Without
PyGObject it falls back to the XEmbed backend (KDE via xembedsniproxy, XFCE,
Cinnamon, MATE...). GNOME without the extension has no tray at all, so closing
the window must not hide it there or it can never be brought back; this module
answers "is there something to hide into?".

The instance socket lets a second launch hand over to the first one ("show
yourself") instead of opening another launcher next to a window hidden in the
tray.
"""

from __future__ import annotations

import contextlib
import os
import shutil
import socket
import subprocess
import tempfile
import threading
from collections.abc import Callable
from pathlib import Path

SNI_WATCHER = "org.kde.StatusNotifierWatcher"
INSTALL_HINT = (
    "Tray icon needs pystray: 'sudo apt install python3-pystray "
    "gir1.2-ayatanaappindicator3-0.1' (Debian/Ubuntu), 'sudo dnf install python3-pystray' "
    "(Fedora) or 'pip install pystray pillow'"
)


def pystray_available() -> tuple[bool, str]:
    """(True, "") if pystray and Pillow import, else (False, why)."""
    try:
        import pystray  # noqa: F401
        from PIL import Image  # noqa: F401
    except Exception as e:  # ImportError, or a backend failing to load (no display, ...)
        return False, f"{type(e).__name__}: {e}"
    return True, ""


_signal_patched = False


def allow_signal_calls_off_main_thread() -> None:
    """Let pystray run on a worker thread.

    pystray's GTK/appindicator backends (0.17.x, as shipped by Fedora) call
    signal.signal(SIGINT, SIG_DFL) inside run(), which Python only allows on the
    main thread, and Tk owns the main thread here. Calls from other threads are
    turned into no-ops; main-thread calls behave exactly as before. Idempotent.
    """
    global _signal_patched
    if _signal_patched:
        return
    import signal

    original = signal.signal

    def signal_main_thread_only(signalnum, handler):
        if threading.current_thread() is threading.main_thread():
            return original(signalnum, handler)
        return signal.getsignal(signalnum)

    signal.signal = signal_main_thread_only
    _signal_patched = True


def backend_name(icon: object) -> str:
    """Short pystray backend name for an Icon: 'appindicator', 'gtk', 'xorg', ..."""
    return type(icon).__module__.rsplit(".", 1)[-1].lstrip("_")


def sni_host_available() -> bool | None:
    """Whether a StatusNotifierItem host (KDE tray, GNOME AppIndicator extension) runs.

    Returns None when it can't be determined (no gdbus/busctl, no session bus).
    """
    if not os.environ.get("DBUS_SESSION_BUS_ADDRESS") and not os.environ.get("XDG_RUNTIME_DIR"):
        return None
    if shutil.which("gdbus"):
        cmd = [
            "gdbus", "call", "--session",
            "--dest", "org.freedesktop.DBus",
            "--object-path", "/org/freedesktop/DBus",
            "--method", "org.freedesktop.DBus.NameHasOwner", SNI_WATCHER,
        ]  # fmt: skip
    elif shutil.which("busctl"):
        cmd = ["busctl", "--user", "status", SNI_WATCHER]
    else:
        return None
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=3)
    except (OSError, subprocess.SubprocessError):
        return None
    if cmd[0] == "gdbus":
        if r.returncode != 0:
            return None
        return "true" in r.stdout
    return r.returncode == 0


def can_hide_to_tray(backend: str, sni_host: bool | None) -> bool:
    """Whether closing the window may hide it: only if the icon can actually be seen.

    The appindicator backend shows nothing without an SNI host. The XEmbed
    backends (xorg, gtk) can't be checked cheaply, so they're trusted.
    """
    if backend == "appindicator":
        return sni_host is not False
    return True


# --- single instance -------------------------------------------------------


def instance_socket_path() -> Path:
    """Per-user socket path; $XDG_RUNTIME_DIR is private to the user."""
    base = os.environ.get("XDG_RUNTIME_DIR") or tempfile.gettempdir()
    return Path(base) / f"minecraft-launcher-{os.getuid()}.sock"


def notify_running_instance(
    path: Path | None = None, timeout: float = 1.0, command: bytes = b"show"
) -> bool:
    """Ask an already running GUI to show its window. True if one answered.

    command=b"ping" only checks that one is listening.
    """
    path = path or instance_socket_path()
    if not path.exists():
        return False
    try:
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as s:
            s.settimeout(timeout)
            s.connect(str(path))
            s.sendall(command + b"\n")
            return s.recv(16).startswith(b"ok")
    except OSError:
        return False


class InstanceServer:
    """Listens on the instance socket and calls on_show() for each 'show' request.

    on_show runs on the server thread; the GUI must marshal to Tk itself.
    """

    def __init__(self, on_show: Callable[[], None], path: Path | None = None):
        self.path = path or instance_socket_path()
        self._on_show = on_show
        self._sock: socket.socket | None = None
        self._thread: threading.Thread | None = None

    def start(self) -> bool:
        """Bind and serve in a daemon thread. False if another instance holds the socket."""
        if notify_running_instance(self.path, timeout=0.3, command=b"ping"):
            return False
        with contextlib.suppress(FileNotFoundError):
            self.path.unlink()  # stale socket from a crashed run
        sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        try:
            sock.bind(str(self.path))
            self.path.chmod(0o600)
            sock.listen(4)
        except OSError:
            sock.close()
            return False
        self._sock = sock
        self._thread = threading.Thread(target=self._serve, daemon=True, name="instance-socket")
        self._thread.start()
        return True

    def _serve(self) -> None:
        sock = self._sock
        while sock is not None:
            try:
                conn, _ = sock.accept()
            except OSError:
                return  # closed
            with conn:
                try:
                    conn.settimeout(1.0)
                    cmd = conn.recv(16).strip()
                    if cmd == b"show":
                        self._on_show()
                    if cmd in (b"show", b"ping"):
                        conn.sendall(b"ok\n")
                except OSError:
                    pass

    def close(self) -> None:
        sock, self._sock = self._sock, None
        if sock is not None:
            # shutdown() wakes the blocked accept(); close() alone may not on Linux.
            with contextlib.suppress(OSError):
                sock.shutdown(socket.SHUT_RDWR)
            sock.close()
            with contextlib.suppress(FileNotFoundError):
                self.path.unlink()
