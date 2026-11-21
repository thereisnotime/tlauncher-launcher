"""
GUI interface for Minecraft Launcher.
Provides graphical Tkinter-based interaction.
"""

import os
import threading
import tkinter as tk

from ui.common import APP_BUILD, APP_VERSION
from ui.console import ConsoleMixin
from ui.container_control import ContainerControlMixin
from ui.doctor import DoctorMixin
from ui.layout import LayoutMixin
from ui.monitor import ResourceMonitorMixin
from ui.profile_import import ProfileImportMixin
from ui.profile_info import ProfileInfoMixin
from ui.profiles import ProfilesMixin
from ui.settings import SettingsMixin
from ui.state import ContainerStateMixin
from ui.theme import ThemeMixin
from ui.tray import TrayMixin
from ui.updates import UpdatesMixin

__all__ = ["APP_VERSION", "MinecraftLauncherGUI"]


class MinecraftLauncherGUI(
    ThemeMixin,
    LayoutMixin,
    ConsoleMixin,
    SettingsMixin,
    ContainerStateMixin,
    ContainerControlMixin,
    DoctorMixin,
    UpdatesMixin,
    ResourceMonitorMixin,
    ProfilesMixin,
    ProfileImportMixin,
    ProfileInfoMixin,
    TrayMixin,
):
    """Main GUI application for Minecraft Launcher."""

    def __init__(self):
        """Initialize the GUI."""
        self.window = tk.Tk()
        self.window.title(f"Minecraft Launcher Launcher v{APP_BUILD}")
        self.window.minsize(1050, 750)
        self.window.resizable(True, True)
        # Size relative to the screen so the layout isn't cramped on QHD/HiDPI,
        # where a fixed 1100px window leaves the buttons and labels cluttered in
        # a small corner. Clamp to a sane range and center on screen.
        self.window.update_idletasks()
        _sw = self.window.winfo_screenwidth()
        _sh = self.window.winfo_screenheight()
        _w = max(1100, min(int(_sw * 0.66), 1700))
        _h = max(800, min(int(_sh * 0.80), 1050))
        _x = max(0, (_sw - _w) // 2)
        _y = max(0, (_sh - _h) // 3)
        self.window.geometry(f"{_w}x{_h}+{_x}+{_y}")

        # Modern theme and styling
        self._setup_theme()

        # X11: window icon and class so taskbar/dock shows our icon
        self._set_window_icon()
        # WM_CLASS for taskbar/dock (wm_class not available on all Tk builds)
        try:
            self.window.tk.call(
                "wm", "class", str(self.window), "minecraft-launcher", "MinecraftLauncher"
            )
        except (AttributeError, tk.TclError):
            pass

        self.config = {}
        self.detected = {}
        self._user_requested_stop = False
        self._monitor_enabled = False
        self._monitor_job = None

        # Get CPU core count for normalizing stats
        self._cpu_cores = os.cpu_count() or 1

        self._svc_poll_job = None
        # Cross-thread poll results. Workers only WRITE these plain values; the
        # main-thread `after` ticks READ them and update the UI. This keeps all
        # Tk access on the main thread (tkinter is not thread-safe).
        self._svc_result = None
        self._svc_worker_busy = False
        self._last_running = None
        self._state_worker_busy = False
        # Monotonic timestamp of the last start/stop/restart action (0 = none in
        # progress). The state poller leaves the control buttons alone while a
        # transition is in flight, but only for a bounded window so a missed
        # "started" signal can't freeze the buttons forever (see _in_transition).
        self._transition_at = 0.0
        self._state_poll_job = None
        # Compose v2 install offer: declined is remembered for this session only.
        self._compose_install_declined = False
        self._compose_install_busy = False
        self._create_widgets()
        self._detect_and_load()
        self._init_tray()
        threading.Thread(target=self._check_for_updates_async, daemon=True).start()
        self.window.after(3000, self._check_pack_updates_async)
        self.window.after(1500, self._schedule_service_poll)
        self.window.after(2000, self._schedule_state_poll)

    def run(self):
        """Start the GUI main loop."""
        self.window.mainloop()
