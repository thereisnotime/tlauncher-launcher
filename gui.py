"""
GUI interface for Minecraft Launcher.
Provides graphical Tkinter-based interaction.
"""

import os
import threading
import tkinter as tk
from tkinter import scrolledtext, ttk

from core.config import (
    DEFAULT_JAVA,
    DEFAULT_MEMORY,
    JAVA_VERSIONS,
    MEMORY_LIMITS,
)
from ui.common import APP_VERSION
from ui.config import ConfigMixin
from ui.console import ConsoleMixin
from ui.container_control import ContainerControlMixin
from ui.doctor import DoctorMixin
from ui.monitor import ResourceMonitorMixin
from ui.profile_import import ProfileImportMixin
from ui.profile_info import ProfileInfoMixin
from ui.profiles import ProfilesMixin
from ui.state import ContainerStateMixin
from ui.theme import ThemeMixin
from ui.updates import UpdatesMixin

__all__ = ["APP_VERSION", "MinecraftLauncherGUI"]


class MinecraftLauncherGUI(
    ThemeMixin,
    ResourceMonitorMixin,
    ProfilesMixin,
    ProfileImportMixin,
    ProfileInfoMixin,
    ContainerStateMixin,
    UpdatesMixin,
    ConfigMixin,
    ContainerControlMixin,
    DoctorMixin,
    ConsoleMixin,
):
    """Main GUI application for Minecraft Launcher."""

    def __init__(self):
        """Initialize the GUI."""
        self.window = tk.Tk()
        self.window.title("Minecraft Launcher Launcher")
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
                "wm", "class", self.window._w, "minecraft-launcher", "MinecraftLauncher"
            )
        except (AttributeError, tk.TclError):
            pass

        self.config = {}
        self.detected = {}
        self.manager = None
        self._user_requested_stop = False
        self._monitor_enabled = False
        self._monitor_job = None
        self._container_pid = None

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
        threading.Thread(target=self._check_for_updates_async, daemon=True).start()
        self.window.after(1500, self._schedule_service_poll)
        self.window.after(2000, self._schedule_state_poll)

    def _create_widgets(self):
        """Create all GUI widgets."""
        # Main container with better padding
        main_frame = ttk.Frame(self.window, padding="20")
        main_frame.grid(row=0, column=0, sticky=(tk.W, tk.E, tk.N, tk.S))
        self.window.columnconfigure(0, weight=1)
        self.window.rowconfigure(0, weight=1)

        # Create left and right frames for two-column layout
        left_frame = ttk.Frame(main_frame)
        left_frame.grid(row=0, column=0, sticky=(tk.W, tk.E, tk.N, tk.S), padx=(0, 10))

        right_frame = ttk.Frame(main_frame)
        right_frame.grid(row=0, column=1, sticky=(tk.W, tk.E, tk.N, tk.S))

        main_frame.columnconfigure(0, weight=2)  # Left side for controls
        main_frame.columnconfigure(1, weight=1)  # Right side for monitor
        main_frame.rowconfigure(0, weight=1)

        # Header with title
        header_frame = ttk.Frame(left_frame)
        header_frame.grid(row=0, column=0, columnspan=2, sticky=(tk.W, tk.E), pady=(0, 15))

        title_label = ttk.Label(
            header_frame,
            text="⛏ Minecraft Launcher Launcher",
            font=("Segoe UI", 16, "bold"),
            foreground=self.colors["accent"],
        )
        title_label.pack(side=tk.LEFT)

        subtitle_label = ttk.Label(
            header_frame,
            text="Containerized TLauncher",
            font=("Segoe UI", 9),
            foreground=self.colors["fg"],
        )
        subtitle_label.pack(side=tk.LEFT, padx=(10, 0))

        version_label = ttk.Label(
            header_frame,
            text=f"v{APP_VERSION}",
            font=("Segoe UI", 9),
            foreground="#666666",
        )
        version_label.pack(side=tk.RIGHT)

        # Configuration Frame - cleaner layout without detected labels
        detect_frame = ttk.LabelFrame(left_frame, text="⚙ Configuration", padding="12")
        detect_frame.grid(row=1, column=0, columnspan=2, sticky=(tk.W, tk.E), pady=(0, 12))

        # Runtime
        ttk.Label(detect_frame, text="Runtime:", font=("Segoe UI", 10)).grid(
            row=0, column=0, sticky=tk.W, padx=(0, 8)
        )
        self.runtime_var = tk.StringVar()
        self.runtime_combo = ttk.Combobox(
            detect_frame,
            textvariable=self.runtime_var,
            values=["auto", "podman", "docker"],
            state="readonly",
            width=14,
        )
        self.runtime_combo.grid(row=0, column=1, sticky=tk.W, padx=(0, 20))
        self.runtime_status_label = ttk.Label(
            detect_frame, text="", foreground="gray", font=("Segoe UI", 8)
        )
        self.runtime_status_label.grid(row=0, column=2, sticky=tk.W)

        # GPU
        ttk.Label(detect_frame, text="GPU:", font=("Segoe UI", 10)).grid(
            row=0, column=3, sticky=tk.W, padx=(0, 8)
        )
        self.gpu_var = tk.StringVar()
        self.gpu_combo = ttk.Combobox(
            detect_frame,
            textvariable=self.gpu_var,
            values=["auto", "nvidia", "amd", "intel"],
            state="readonly",
            width=14,
        )
        self.gpu_combo.grid(row=0, column=4, sticky=tk.W, padx=(0, 20))
        self.gpu_status_label = ttk.Label(
            detect_frame, text="", foreground="gray", font=("Segoe UI", 8)
        )
        self.gpu_status_label.grid(row=0, column=5, sticky=tk.W)

        # Display
        ttk.Label(detect_frame, text="Display:", font=("Segoe UI", 10)).grid(
            row=1, column=0, sticky=tk.W, padx=(0, 8), pady=(10, 0)
        )
        self.display_var = tk.StringVar()
        self.display_combo = ttk.Combobox(
            detect_frame,
            textvariable=self.display_var,
            values=["auto", "x11", "wayland", "wslg"],
            state="readonly",
            width=14,
        )
        self.display_combo.grid(row=1, column=1, sticky=tk.W, pady=(10, 0), padx=(0, 20))
        self.display_status_label = ttk.Label(
            detect_frame, text="", foreground="gray", font=("Segoe UI", 8)
        )
        self.display_status_label.grid(row=1, column=2, sticky=tk.W, pady=(10, 0))

        # Audio
        ttk.Label(detect_frame, text="Audio:", font=("Segoe UI", 10)).grid(
            row=1, column=3, sticky=tk.W, padx=(0, 8), pady=(10, 0)
        )
        self.audio_var = tk.StringVar()
        self.audio_combo = ttk.Combobox(
            detect_frame,
            textvariable=self.audio_var,
            values=["auto", "pulseaudio", "none"],
            state="readonly",
            width=14,
        )
        self.audio_combo.grid(row=1, column=4, sticky=tk.W, pady=(10, 0), padx=(0, 20))
        self.audio_status_label = ttk.Label(
            detect_frame, text="", foreground="gray", font=("Segoe UI", 8)
        )
        self.audio_status_label.grid(row=1, column=5, sticky=tk.W, pady=(10, 0))

        # Java (not detected: pick per Minecraft version; each gets its own image)
        ttk.Label(detect_frame, text="Java:", font=("Segoe UI", 10)).grid(
            row=2, column=0, sticky=tk.W, padx=(0, 8), pady=(10, 0)
        )
        self.java_var = tk.StringVar(value=DEFAULT_JAVA)
        self.java_combo = ttk.Combobox(
            detect_frame,
            textvariable=self.java_var,
            values=list(JAVA_VERSIONS),
            state="readonly",
            width=14,
        )
        self.java_combo.grid(row=2, column=1, sticky=tk.W, pady=(10, 0), padx=(0, 20))
        ttk.Label(
            detect_frame,
            text="(TLauncher only)",
            foreground="gray",
            font=("Segoe UI", 8),
        ).grid(row=2, column=2, sticky=tk.W, pady=(10, 0))

        # Memory (container cap; the game's -Xmx is set inside TLauncher)
        ttk.Label(detect_frame, text="Memory:", font=("Segoe UI", 10)).grid(
            row=2, column=3, sticky=tk.W, padx=(0, 8), pady=(10, 0)
        )
        self.memory_var = tk.StringVar(value=DEFAULT_MEMORY)
        self.memory_combo = ttk.Combobox(
            detect_frame,
            textvariable=self.memory_var,
            values=list(MEMORY_LIMITS),
            state="readonly",
            width=14,
        )
        self.memory_combo.grid(row=2, column=4, sticky=tk.W, pady=(10, 0), padx=(0, 20))
        ttk.Label(
            detect_frame,
            text="(container cap)",
            foreground="gray",
            font=("Segoe UI", 8),
        ).grid(row=2, column=5, sticky=tk.W, pady=(10, 0))

        detect_frame.columnconfigure(5, weight=1)

        # Control Buttons Frame — 2-row grid so buttons never squish
        control_frame = ttk.Frame(left_frame)
        control_frame.grid(row=2, column=0, columnspan=2, sticky=(tk.W, tk.E), pady=(0, 15))
        for col in range(3):
            control_frame.columnconfigure(col, weight=1)

        self.btn_start = ttk.Button(control_frame, text="▶  Start", command=self.start_minecraft)
        self.btn_start.grid(row=0, column=0, sticky=(tk.W, tk.E), padx=(0, 4), pady=(0, 4))

        self.btn_stop = ttk.Button(
            control_frame, text="⏹  Stop", command=self.stop_minecraft, state=tk.DISABLED
        )
        self.btn_stop.grid(row=0, column=1, sticky=(tk.W, tk.E), padx=4, pady=(0, 4))

        self.btn_restart = ttk.Button(
            control_frame,
            text="🔄  Restart",
            command=self.restart_minecraft,
            state=tk.DISABLED,
        )
        self.btn_restart.grid(row=0, column=2, sticky=(tk.W, tk.E), padx=(4, 0), pady=(0, 4))

        self.btn_doctor = ttk.Button(control_frame, text="🩺  Doctor", command=self.run_doctor)
        self.btn_doctor.grid(row=1, column=0, sticky=(tk.W, tk.E), padx=(0, 4))

        self.btn_save = ttk.Button(
            control_frame, text="💾  Save Config", command=self.save_configuration
        )
        self.btn_save.grid(row=1, column=1, sticky=(tk.W, tk.E), padx=4)

        self.btn_edit = ttk.Button(
            control_frame, text="✏  Edit Config", command=self.edit_configuration
        )
        self.btn_edit.grid(row=1, column=2, sticky=(tk.W, tk.E), padx=(4, 0))

        self.btn_rebuild = ttk.Button(
            control_frame, text="🔨  Rebuild Image", command=self.rebuild_image
        )
        self.btn_rebuild.grid(
            row=2, column=0, columnspan=2, sticky=(tk.W, tk.E), padx=(0, 4), pady=(4, 0)
        )

        self.btn_report_bug = ttk.Button(
            control_frame, text="🐛  Report Bug", command=self.report_bug
        )
        self.btn_report_bug.grid(row=2, column=2, sticky=(tk.W, tk.E), padx=(4, 0), pady=(4, 0))

        # Make left_frame columns expand properly
        left_frame.columnconfigure(0, weight=1)
        left_frame.columnconfigure(1, weight=1)
        left_frame.rowconfigure(4, weight=1)  # Log frame expands

        # Status Label with icon and better styling
        status_frame = ttk.Frame(left_frame)
        status_frame.grid(row=3, column=0, columnspan=2, sticky=(tk.W, tk.E), pady=(0, 10))

        self.status_label = ttk.Label(
            status_frame,
            text="● Ready",
            font=("Segoe UI", 11, "bold"),
            foreground=self.colors["success"],
        )
        self.status_label.pack(side=tk.LEFT)

        # Update notification — hidden until an update is found, sits between status and services
        self._update_frame = ttk.Frame(status_frame)
        self._update_label = ttk.Label(
            self._update_frame,
            text="",
            font=("Segoe UI", 9),
            foreground="#7cbd3f",
        )
        self._update_label.pack(side=tk.LEFT)
        ttk.Button(
            self._update_frame,
            text="⬆ Update",
            command=self._do_update,
        ).pack(side=tk.LEFT, padx=(6, 0))

        # Runtime availability indicators (right-aligned). Green = the runtime
        # responds to `<rt> ps` (i.e. it's usable to launch the game); gray =
        # not available. Updated on the main thread by _schedule_service_poll.
        self.docker_svc_label = ttk.Label(
            status_frame,
            text="● docker",
            font=("Segoe UI", 9),
            foreground="#555555",
        )
        self.docker_svc_label.pack(side=tk.RIGHT, padx=(8, 0))

        self.podman_svc_label = ttk.Label(
            status_frame,
            text="● podman",
            font=("Segoe UI", 9),
            foreground="#555555",
        )
        self.podman_svc_label.pack(side=tk.RIGHT, padx=(8, 0))

        # Log Output Frame with better styling
        log_frame = ttk.LabelFrame(left_frame, text="📋 Console Output", padding="15")
        log_frame.grid(row=4, column=0, columnspan=2, sticky=(tk.W, tk.E, tk.N, tk.S))
        log_frame.columnconfigure(0, weight=1)
        log_frame.rowconfigure(0, weight=1)

        # Styled scrolled text with dark theme
        self.log_text = scrolledtext.ScrolledText(
            log_frame,
            height=20,
            wrap=tk.WORD,
            bg="#1e1e1e",
            fg="#d4d4d4",
            insertbackground="#7cbd3f",
            selectbackground="#3d3d3d",
            font=("Consolas", 9),
            relief=tk.FLAT,
            borderwidth=0,
        )
        self.log_text.grid(row=0, column=0, sticky=(tk.W, tk.E, tk.N, tk.S), padx=2, pady=2)

        # Log buttons in a frame so they stay visible and aren't cut off
        log_btn_frame = ttk.Frame(log_frame)
        log_btn_frame.grid(row=1, column=0, sticky=(tk.W, tk.E), pady=(8, 2))
        btn_clear = ttk.Button(log_btn_frame, text="Clear Logs", command=self.clear_logs)
        btn_clear.pack(side=tk.LEFT, padx=(0, 5))
        btn_copy = ttk.Button(log_btn_frame, text="Copy all logs", command=self.copy_logs)
        btn_copy.pack(side=tk.LEFT)

        # Right side: Resource Monitor and Profiles
        self._create_resource_monitor(right_frame)
        self._create_profiles_panel(right_frame)

    def run(self):
        """Start the GUI main loop."""
        self.window.mainloop()
