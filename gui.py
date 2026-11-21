"""
GUI interface for Minecraft Launcher.
Provides graphical Tkinter-based interaction.
"""

import os
import platform
import subprocess
import threading
import time
import tkinter as tk
import urllib.parse
import webbrowser
from pathlib import Path
from tkinter import messagebox, scrolledtext, ttk
from typing import Dict

from core.compose_installer import default_target, install_docker_compose
from core.composer import get_command_preview, strip_ansi
from core.config import (
    DEFAULT_JAVA,
    DEFAULT_MEMORY,
    JAVA_VERSIONS,
    MEMORY_LIMITS,
    load_config,
    merge_config,
    normalize_java,
    normalize_memory,
    save_config,
)
from core.container import (
    ContainerManager,
    build_image_command,
    image_exists,
    image_tag,
    start_container_async,
)
from core.detector import detect_compose_provider, detect_system, get_detection_details
from core.log_analyzer import analyze_lines
from core.validator import COMPOSE_V2_MISSING, run_xhost_if_needed, validate_system
from ui.common import APP_DIR, APP_VERSION
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

    def _detect_and_load(self):
        """Detect system and load configuration."""
        self.log("Detecting system configuration...")

        # Detect system
        self.detected = detect_system()

        # Load saved config
        saved = load_config()

        # Merge (saved overrides detection)
        self.config = merge_config(self.detected, saved)

        # Update UI
        self._update_ui_from_config()

        self.log(f"✓ Runtime: {self.detected['runtime']}")
        self.log(f"✓ GPU: {self.detected['gpu']}")
        self.log(f"✓ Display: {self.detected['display']}")
        self.log(f"✓ Audio: {self.detected['audio']}")

        # Check if container is already running
        self._check_existing_container()

    def _update_ui_from_config(self):
        """Update UI dropdowns from current config."""
        self.runtime_var.set(
            "auto"
            if not self.config.get("runtime") or self.config["runtime"] == self.detected["runtime"]
            else self.config["runtime"]
        )
        self.gpu_var.set(
            "auto"
            if not self.config.get("gpu") or self.config["gpu"] == self.detected["gpu"]
            else self.config["gpu"]
        )
        self.display_var.set(
            "auto"
            if not self.config.get("display") or self.config["display"] == self.detected["display"]
            else self.config["display"]
        )
        self.audio_var.set(
            "auto"
            if not self.config.get("audio") or self.config["audio"] == self.detected["audio"]
            else self.config["audio"]
        )
        self.java_var.set(normalize_java(self.config.get("java")))
        self.memory_var.set(normalize_memory(self.config.get("memory")))

        # Show detected values only if different from 'auto'
        self.runtime_status_label.config(
            text=f"({self.detected['runtime']})" if self.runtime_var.get() == "auto" else ""
        )
        self.gpu_status_label.config(
            text=f"({self.detected['gpu']})" if self.gpu_var.get() == "auto" else ""
        )
        self.display_status_label.config(
            text=f"({self.detected['display']})" if self.display_var.get() == "auto" else ""
        )
        self.audio_status_label.config(
            text=f"({self.detected['audio']})" if self.audio_var.get() == "auto" else ""
        )

    def _gather_config(self) -> Dict[str, str]:
        """Gather configuration from UI."""
        runtime = self.runtime_var.get()
        gpu = self.gpu_var.get()
        display = self.display_var.get()
        audio = self.audio_var.get()

        # Convert 'auto' back to detected values
        return {
            "runtime": self.detected["runtime"] if runtime == "auto" else runtime,
            "gpu": self.detected["gpu"] if gpu == "auto" else gpu,
            "display": self.detected["display"] if display == "auto" else display,
            "audio": self.detected["audio"] if audio == "auto" else audio,
            "java": normalize_java(self.java_var.get()),
            "memory": normalize_memory(self.memory_var.get()),
            "auto_xhost": True,
        }

    def start_minecraft(self):
        """Start button handler."""
        # Check if already running
        try:
            runtime = self.detected.get("runtime", "podman")
            result = subprocess.run(
                [runtime, "ps", "--filter", "name=tlauncher", "--format", "{{.Names}}"],
                capture_output=True,
                text=True,
                timeout=3,
            )
            if result.returncode == 0 and "tlauncher" in result.stdout:
                self.log("\n⚠️  Container is already running!")
                messagebox.showinfo(
                    "Already Running",
                    "Minecraft container is already running.\nUse Stop to stop it first.",
                )
                return
        except Exception:
            pass  # If check fails, continue with start

        config = self._gather_config()

        # Build the image automatically if it's missing (first run). No need to
        # click Rebuild manually; that's only for picking up Containerfile edits.
        if not image_exists(config.get("runtime", "podman"), config["java"]):
            self.log(
                f"\nImage {image_tag(config['java'])} not found — building it first (one time)..."
            )
            self.rebuild_image(then_start=True)
            return

        self._do_start(config)

    def _do_start(self, config=None):
        """Validate, set permissions, and launch the container."""
        if config is None:
            config = self._gather_config()

        # Validate
        self.log("\n" + "=" * 50)
        self.log("Validating system...")
        valid, issues = validate_system(config)

        if issues:
            for issue in issues:
                symbol = "✗" if issue.is_blocking() else "⚠"
                self.log(f"{symbol} {issue.message}")
                if issue.fix_hint:
                    self.log(f"  → {issue.fix_hint}")

        if self._offer_compose_install(issues, on_done=lambda: self._do_start(config)):
            return

        if not valid:
            self.log("\n✗ Validation failed. Cannot start.")
            self._update_status("Validation failed", "error")
            messagebox.showerror(
                "Validation Failed", "System validation failed. Check the output for details."
            )
            return

        self.log("✓ Validation passed")

        # Run xhost if needed (x11 and XWayland both use the X server)
        if config["display"] in ("x11", "wayland") and config.get("auto_xhost", True):
            self.log("Setting X11 permissions...")
            if run_xhost_if_needed(config):
                self.log("✓ X11 permissions set")
            else:
                self.log("⚠ Could not set X11 permissions automatically")

        # Show command
        self.log(f"\nCommand: {get_command_preview(config, 'up')}\n")

        # Update UI state. Doctor stays enabled: it's a read-only diagnostic and
        # is useful to run at any time, including while the container is up.
        self._transition_at = time.monotonic()
        self._update_status("Starting...", "warning")
        self.btn_start.config(state=tk.DISABLED)

        # Start container in background thread
        _error_flags = {"nvidia_ldcache": False}

        def output_callback(line):
            self.log(line)
            if "nvidia-container-cli" in line or "ldcache error" in line:
                _error_flags["nvidia_ldcache"] = True

        def started_callback():
            # Launcher GUI is up; run UI update on main thread
            def _on_started():
                self._transition_at = 0.0
                self._update_status("Running", "success")
                self.btn_stop.config(state=tk.NORMAL)
                self.btn_restart.config(state=tk.NORMAL)
                self.log("\n✓ Container started successfully")

            self.window.after(0, _on_started)

        def completion_callback(success):
            # Container process exited; run UI update on main thread
            def _on_exited():
                self._transition_at = 0.0
                self._update_status("Stopped", "gray")
                self.btn_start.config(state=tk.NORMAL)
                self.btn_stop.config(state=tk.DISABLED)
                self.btn_restart.config(state=tk.DISABLED)
                self.btn_doctor.config(state=tk.NORMAL)
                if self._user_requested_stop:
                    self._user_requested_stop = False
                elif success:
                    self.log("\n✓ Container stopped")
                else:
                    self.log("\n✗ Container exited with error")
                    if _error_flags["nvidia_ldcache"]:
                        messagebox.showerror(
                            "NVIDIA Container Error",
                            "The NVIDIA container toolkit reported an ldcache error.\n\n"
                            "This usually means the toolkit is running in legacy mode "
                            "and ldconfig.real failed inside the container.\n\n"
                            "Fix — run one of these and then Start again:\n\n"
                            "  sudo nvidia-ctk runtime configure --runtime=docker\n\n"
                            "  sudo nvidia-ctk runtime configure --runtime=podman\n\n"
                            "If the error persists, try:\n"
                            "  sudo nvidia-ctk config --set "
                            "nvidia-container-runtime.mode=csv",
                        )
                    elif messagebox.askyesno(
                        "Minecraft stopped", "Minecraft exited unexpectedly.\n\nRestart?"
                    ):
                        self.start_minecraft()

                # Always run log analysis; only show output if there are findings
                log_lines = self.log_text.get("1.0", tk.END).splitlines()
                findings = analyze_lines(log_lines)
                if findings:
                    self.log("\n" + "─" * 50)
                    self.log("Log Analysis:")
                    for f in findings:
                        symbol = "✗" if f.level == "error" else "⚠"
                        self.log(f"{symbol} {f.title}")
                        self.log(f"  {f.detail}")
                        for line in f.recommendation.splitlines():
                            self.log(f"  → {line}")
                    self.log("─" * 50)

            self.window.after(0, _on_exited)

        start_container_async(
            config,
            detached=False,
            output_callback=output_callback,
            started_callback=started_callback,
            completion_callback=completion_callback,
        )

    def stop_minecraft(self):
        """Stop button handler."""
        config = self._gather_config()

        self._user_requested_stop = True
        self._transition_at = time.monotonic()
        self.log("\n" + "=" * 50)
        self.log("Stopping container...")
        self._update_status("Stopping...", "warning")

        def stop_worker():
            manager = ContainerManager(config)
            success = manager.stop()

            def _on_stop_done():
                self._transition_at = 0.0
                if success:
                    self._update_status("Stopped", "gray")
                    self.btn_start.config(state=tk.NORMAL)
                    self.btn_stop.config(state=tk.DISABLED)
                    self.btn_restart.config(state=tk.DISABLED)
                    self.btn_doctor.config(state=tk.NORMAL)
                    self.log("✓ Container stopped")
                else:
                    self._update_status("Running", "success")
                    self.log("✗ Failed to stop container")

            self.window.after(0, _on_stop_done)

        threading.Thread(target=stop_worker, daemon=True).start()

    def restart_minecraft(self):
        """Restart button handler: stop the container, then start it fresh.

        Rather than the blocking ContainerManager.restart() (which never signals
        "started", so the status and buttons never resync), this stops the
        current container and re-enters the normal start path (_do_start) so the
        started/exited callbacks, status, and button states all update correctly.
        """
        config = self._gather_config()

        self.log("\n" + "=" * 50)
        self.log("Restarting container...")
        self._update_status("Restarting...", "warning")
        self._transition_at = time.monotonic()
        self.btn_restart.config(state=tk.DISABLED)
        self.btn_stop.config(state=tk.DISABLED)

        # Flag the stop as intentional so the currently-running start()'s
        # completion callback doesn't prompt "Minecraft exited unexpectedly".
        self._user_requested_stop = True

        def restart_worker():
            manager = ContainerManager(config)
            manager.stop()
            # Re-launch on the main thread through the normal start flow.
            self.window.after(0, lambda: self._do_start(config))

        threading.Thread(target=restart_worker, daemon=True).start()

    def rebuild_image(self, then_start=False):
        """Rebuild the container image using the configured runtime.

        If then_start is True, automatically start the container once the build
        succeeds (used when Start triggers a first-run build).
        """

        config = self._gather_config()
        runtime = config.get("runtime", "podman")
        repo_dir = str(APP_DIR)

        self.log(f"\n{'=' * 50}")
        self.log(f"🔨 Building {image_tag(config['java'])} with {runtime}...")
        self.log("This may take several minutes on the first run.\n")

        self.btn_rebuild.config(state=tk.DISABLED)
        self.btn_start.config(state=tk.DISABLED)

        def _build():
            try:
                proc = subprocess.Popen(
                    build_image_command(runtime, config["java"]),
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    text=True,
                    cwd=repo_dir,
                )
                for line in proc.stdout:
                    stripped = line.rstrip()
                    self.window.after(0, lambda msg=stripped: self.log(msg))
                proc.wait()
                success = proc.returncode == 0
            except FileNotFoundError:
                self.window.after(
                    0, lambda: self.log(f"✗ '{runtime}' not found — is it installed?")
                )
                success = False
            except Exception as exc:
                err = str(exc)
                self.window.after(0, lambda msg=err: self.log(f"✗ Build error: {msg}"))
                success = False

            def _on_done():
                self.btn_rebuild.config(state=tk.NORMAL)
                self.btn_start.config(state=tk.NORMAL)
                if success:
                    if then_start:
                        self.log("\n✓ Image built — starting Minecraft...")
                        self._do_start()
                    else:
                        self.log("\n✓ Image rebuilt — you can now start Minecraft")
                        messagebox.showinfo(
                            "Build Complete",
                            "Container image rebuilt successfully.\nYou can now start Minecraft.",
                        )
                else:
                    self.log("\n✗ Build failed — check the output above")
                    messagebox.showerror(
                        "Build Failed",
                        "Container image build failed.\nCheck the console output for details.",
                    )

            self.window.after(0, _on_done)

        threading.Thread(target=_build, daemon=True).start()

    def report_bug(self):
        """Open a pre-filled GitHub bug report with current system info."""

        config = self._gather_config()
        runtime = config.get("runtime", "unknown")
        gpu = config.get("gpu", "unknown")
        display = config.get("display", "unknown")
        audio = config.get("audio", "unknown")

        try:
            runtime_version = (
                subprocess.check_output([runtime, "--version"], text=True, timeout=5)
                .strip()
                .splitlines()[0]
            )
        except Exception:
            runtime_version = "unknown"

        os_info = platform.platform()

        log_raw = self.log_text.get("1.0", "end-1c")
        recent_logs = "\n".join(log_raw.splitlines()[-40:])

        tb = "```"
        body = f"""## Description

<!-- Clear description of what the bug is -->

## Steps to Reproduce

1.
2.
3.

## Expected Behavior

<!-- What you expected to happen -->

## Actual Behavior

<!-- What actually happened -->

## System Information

- **OS**: {os_info}
- **Launcher Version**: {APP_VERSION}
- **Runtime**: {runtime} ({runtime_version})
- **GPU**: {gpu}
- **Display Server**: {display}
- **Audio**: {audio}

## Doctor Output

{tb}text
(run ./minecraft.py doctor and paste here)
{tb}

## Console Logs

{tb}text
{recent_logs}
{tb}

## Additional Context

<!-- Screenshots, links, or any other relevant information -->
"""

        params = urllib.parse.urlencode(
            {
                "template": "bug_report.md",
                "title": "[BUG] ",
                "body": body,
            }
        )
        webbrowser.open(f"https://github.com/thereisnotime/tlauncher-launcher/issues/new?{params}")

    def run_doctor(self):
        """Doctor button handler - run validation."""
        self.log("\n" + "=" * 50)
        self.log("Running system diagnostics...\n")

        details = get_detection_details()

        # Show detection details (kept in sync with the CLI doctor output)
        rt = details["runtime"]
        rt_status = "✓" if rt["available"] else "✗"
        self.log(f"{rt_status} Runtime: {rt['value']} ({rt['path']})")

        gpu = details["gpu"]
        gpu_status = "✓" if gpu["devices_exist"] else "⚠"
        self.log(f"{gpu_status} GPU: {gpu['details']}")

        disp = details["display"]
        resolution = disp.get("resolution") or "unknown"
        self.log(
            f"✓ Display: {disp['value']} ({resolution}, session: {disp['session_type']}, "
            f"var: {disp['display_var']})"
        )

        aud = details["audio"]
        audio_status = "✓" if aud["value"] != "none" else "⚠"
        self.log(f"{audio_status} Audio: {aud['details']}")

        scale = details["ui_scale"]["value"]
        if scale > 1.0:
            self.log(f"  Host scale: {scale:g}x (not applied; export JAVA_UI_SCALE to force)")
        else:
            self.log("  Host scale: 1x")

        # Validate
        config = self._gather_config()
        self.log("\nValidation:")
        valid, issues = validate_system(config)

        if issues:
            for issue in issues:
                symbol = "✗" if issue.is_blocking() else "⚠"
                self.log(f"{symbol} {issue.message}")
                if issue.fix_hint:
                    self.log(f"  → {issue.fix_hint}")
        else:
            self.log("✓ No issues found")

        if self._offer_compose_install(issues, on_done=self.run_doctor):
            return

        if valid:
            self.log("\n✓ System ready!")
            messagebox.showinfo("System Check", "System is ready to run Minecraft!")
        else:
            self.log("\n✗ System has errors")
            messagebox.showwarning(
                "System Check", "System has validation errors. Check the output for details."
            )

    def _offer_compose_install(self, issues, on_done=None) -> bool:
        """Offer to install Docker Compose v2 if validation says podman lacks it.

        Returns True if the install was started; the caller should stop there,
        and on_done runs on the main thread once the install has finished.
        """
        if self._compose_install_declined or self._compose_install_busy:
            return False
        if not any(getattr(i, "code", None) == COMPOSE_V2_MISSING for i in issues):
            return False

        if not messagebox.askyesno(
            "Docker Compose v2",
            "Podman has no Docker Compose v2 to use, so it falls back to the old "
            "python podman-compose (or nothing at all).\n\n"
            f"Install Docker Compose v2 to ~/.local/bin?\n({default_target()})",
        ):
            self._compose_install_declined = True
            self.log("(Skipping the Docker Compose v2 install for this session)")
            return False

        self.install_compose(on_done=on_done)
        return True

    def install_compose(self, on_done=None):
        """Download Docker Compose v2 in the background, then re-check the provider."""

        self._compose_install_busy = True
        start_state = str(self.btn_start.cget("state"))
        self.btn_start.config(state=tk.DISABLED)
        self.log(f"\n{'=' * 50}")
        self.log("Installing Docker Compose v2...")

        def _log(msg):
            self.window.after(0, lambda m=msg: self.log(m))

        def _worker():
            result = install_docker_compose(log=_log)
            # Re-run provider detection off the main thread (it execs the binary).
            provider = detect_compose_provider("podman") if result.ok else ""

            def _finish():
                self._compose_install_busy = False
                self.btn_start.config(state=start_state)
                if result.ok:
                    self.log(f"✓ {result.message}")
                    if provider:
                        self.log(f"✓ podman compose will use {provider}")
                    else:
                        self.log("⚠ Installed, but it still isn't detected as Compose v2")
                else:
                    self.log(f"✗ {result.message}")
                    messagebox.showerror("Install Failed", result.message)
                # Either way, don't ask again this session.
                self._compose_install_declined = True
                if on_done:
                    on_done()

            self.window.after(0, _finish)

        threading.Thread(target=_worker, daemon=True).start()

    def save_configuration(self):
        """Save current configuration."""
        config = self._gather_config()

        # Save with 'auto' converted to empty strings
        save_data = {
            "runtime": "" if self.runtime_var.get() == "auto" else config["runtime"],
            "gpu": "" if self.gpu_var.get() == "auto" else config["gpu"],
            "display": "" if self.display_var.get() == "auto" else config["display"],
            "audio": "" if self.audio_var.get() == "auto" else config["audio"],
            "java": config["java"],
            "memory": config["memory"],
            "auto_xhost": True,
        }

        if save_config(save_data):
            self.log("\n✓ Configuration saved")
            messagebox.showinfo("Configuration Saved", "Your configuration has been saved.")
        else:
            self.log("\n✗ Failed to save configuration")
            messagebox.showerror("Save Failed", "Could not save configuration.")

    def edit_configuration(self):
        """Open configuration file in text editor."""

        # Get config file path
        config_dir = Path.home() / ".config" / "minecraft-launcher"
        config_file = config_dir / "config.yaml"

        # Create config directory if it doesn't exist
        config_dir.mkdir(parents=True, exist_ok=True)

        # Create empty config file if it doesn't exist
        if not config_file.exists():
            config_file.write_text(
                "# Minecraft Launcher Launcher Configuration\n# Leave values empty to use auto-detection\n\nruntime: ''\ngpu: ''\ndisplay: ''\naudio: ''\nauto_xhost: true\n"
            )
            self.log("\n✓ Created new config file")

        # Open in default text editor
        try:
            if os.name == "posix":  # Linux/Unix
                subprocess.Popen(["xdg-open", str(config_file)])
            elif os.name == "nt":  # Windows
                os.startfile(str(config_file))
            else:
                messagebox.showinfo("Config Location", f"Config file location:\n{config_file}")
                return

            self.log(f"\n✓ Opening config file: {config_file}")
            messagebox.showinfo(
                "Config Editor",
                f"Opening config file in your default editor:\n{config_file}\n\nEdit and save the file, then restart the launcher to apply changes.",
            )
        except Exception as e:
            self.log(f"\n✗ Failed to open config file: {e}")
            messagebox.showerror(
                "Failed to Open",
                f"Could not open config file.\nLocation: {config_file}\n\nError: {e}",
            )

    def clear_logs(self):
        """Clear the log output."""
        self.log_text.delete("1.0", tk.END)

    def copy_logs(self):
        """Copy full log content to the clipboard."""
        content = self.log_text.get("1.0", tk.END)
        if content.strip():
            self.window.clipboard_clear()
            self.window.clipboard_append(content)
            self.window.update_idletasks()
            self.log("(Logs copied to clipboard)")

    def log(self, message: str):
        """Append message to log output."""
        self.log_text.insert(tk.END, strip_ansi(message) + "\n")
        self.log_text.see(tk.END)
        self.log_text.update()

    def _update_status(self, text: str, color: str = "success"):
        """Update status label with colored indicator."""
        # Map color names to actual colors
        color_map = {
            "success": self.colors["success"],
            "green": self.colors["success"],
            "warning": self.colors["warning"],
            "orange": self.colors["warning"],
            "error": self.colors["error"],
            "red": self.colors["error"],
            "info": self.colors["info"],
            "gray": "#888888",
            "black": self.colors["fg"],
        }

        actual_color = color_map.get(color, color)

        # Add status indicator dot
        if "Running" in text:
            status_text = "● " + text.replace("Status: ", "")
        elif "Starting" in text or "Stopping" in text or "Restarting" in text:
            status_text = "◐ " + text.replace("Status: ", "")
        elif "Stopped" in text or "Ready" in text:
            status_text = "○ " + text.replace("Status: ", "")
        elif "Failed" in text or "Error" in text:
            status_text = "✗ " + text.replace("Status: ", "")
        else:
            status_text = "● " + text.replace("Status: ", "")

        self.status_label.config(text=status_text, foreground=actual_color)

    def run(self):
        """Start the GUI main loop."""
        self.window.mainloop()
