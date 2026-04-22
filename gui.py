"""
GUI interface for Minecraft Launcher.
Provides graphical Tkinter-based interaction.
"""

import threading
import tkinter as tk
from pathlib import Path
from tkinter import messagebox, scrolledtext, ttk
from typing import Dict

from core.composer import get_command_preview
from core.config import load_config, merge_config, save_config
from core.container import ContainerManager, start_container_async
from core.detector import detect_system, get_detection_details
from core.validator import run_xhost_if_needed, validate_system


def _read_app_version() -> str:
    import re

    try:
        toml = (Path(__file__).parent / "pyproject.toml").read_text()
        m = re.search(r'^version\s*=\s*"([^"]+)"', toml, re.MULTILINE)
        return m.group(1) if m else "1.0.0"
    except Exception:
        return "1.0.0"


APP_VERSION = _read_app_version()


class MinecraftLauncherGUI:
    """Main GUI application for Minecraft Launcher."""

    def __init__(self):
        """Initialize the GUI."""
        self.window = tk.Tk()
        self.window.title("Minecraft Launcher Launcher")
        self.window.geometry("1100x800")
        self.window.minsize(1050, 750)
        self.window.resizable(True, True)

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
        import os

        self._cpu_cores = os.cpu_count() or 1

        self._svc_poll_job = None
        self._create_widgets()
        self._detect_and_load()
        threading.Thread(target=self._check_for_updates_async, daemon=True).start()
        self.window.after(1500, self._schedule_service_poll)

    def _setup_theme(self):
        """Set up modern theme and colors."""
        style = ttk.Style()

        # Try to use a better theme if available
        available_themes = style.theme_names()
        if "clam" in available_themes:
            style.theme_use("clam")
        elif "alt" in available_themes:
            style.theme_use("alt")

        # Custom color scheme - Minecraft-inspired greens and modern grays
        bg_color = "#2b2b2b"  # Dark gray background
        fg_color = "#e8e8e8"  # Light text
        accent_color = "#7cbd3f"  # Minecraft grass green
        button_bg = "#3d3d3d"  # Button background
        button_active = "#4a4a4a"  # Button hover

        # Configure window background
        self.window.configure(bg=bg_color)

        # Configure styles
        style.configure("TFrame", background=bg_color)
        style.configure("TLabel", background=bg_color, foreground=fg_color, font=("Segoe UI", 10))
        style.configure(
            "TLabelframe", background=bg_color, foreground=fg_color, bordercolor=accent_color
        )
        style.configure(
            "TLabelframe.Label",
            background=bg_color,
            foreground=accent_color,
            font=("Segoe UI", 10, "bold"),
        )

        # Button styling
        style.configure(
            "TButton",
            background=button_bg,
            foreground=fg_color,
            bordercolor=accent_color,
            focuscolor=accent_color,
            font=("Segoe UI", 9),
            padding=8,
        )
        style.map(
            "TButton",
            background=[("active", button_active), ("pressed", accent_color)],
            foreground=[("active", fg_color)],
        )

        # Combobox styling
        style.configure(
            "TCombobox",
            fieldbackground=button_bg,
            background=button_bg,
            foreground=fg_color,
            arrowcolor=accent_color,
            selectbackground=accent_color,
            selectforeground=fg_color,
        )

        style.map(
            "TCombobox",
            fieldbackground=[("readonly", button_bg)],
            selectbackground=[("readonly", accent_color)],
            selectforeground=[("readonly", fg_color)],
        )

        # Configure combobox dropdown listbox colors
        self.window.option_add("*TCombobox*Listbox.background", button_bg)
        self.window.option_add("*TCombobox*Listbox.foreground", fg_color)
        self.window.option_add("*TCombobox*Listbox.selectBackground", accent_color)
        self.window.option_add("*TCombobox*Listbox.selectForeground", fg_color)
        self.window.option_add("*TCombobox*Listbox.font", ("Segoe UI", 10))

        # Configure colors for status labels
        self.colors = {
            "bg": bg_color,
            "fg": fg_color,
            "accent": accent_color,
            "success": "#4caf50",
            "warning": "#ff9800",
            "error": "#f44336",
            "info": "#2196f3",
        }

    def _set_window_icon(self):
        """Set the window icon for taskbar/dock (X11). Keeps a reference to avoid GC."""
        icon_path = Path(__file__).parent / "icon.png"
        if not icon_path.is_file():
            return
        try:
            # Try standard Tk PhotoImage (PNG supported on many Linux Tk builds)
            self._icon_photo = tk.PhotoImage(file=str(icon_path))
            self.window.iconphoto(True, self._icon_photo)
        except tk.TclError:
            try:
                # Fallback: Pillow if installed
                from PIL import Image, ImageTk

                img = Image.open(icon_path)
                self._icon_photo = ImageTk.PhotoImage(img)
                self.window.iconphoto(True, self._icon_photo)
            except (ImportError, OSError):
                pass

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
            values=["auto", "nvidia", "amd"],
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
            values=["auto", "x11", "wayland"],
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
        self.btn_rebuild.grid(row=2, column=0, columnspan=3, sticky=(tk.W, tk.E), pady=(4, 0))

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

        # Service status indicators (right-aligned, updated by _poll_service_status)
        self.docker_svc_label = ttk.Label(
            status_frame,
            text="● docker",
            font=("Segoe UI", 9),
            foreground="#555555",
        )
        self.docker_svc_label.pack(side=tk.RIGHT, padx=(8, 0))

        self.podman_svc_label = ttk.Label(
            status_frame,
            text="● podman.socket",
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

    def _create_resource_monitor(self, parent_frame):
        """Create resource monitoring panel."""
        monitor_frame = ttk.LabelFrame(parent_frame, text="📊 Resource Monitor", padding="10")
        monitor_frame.grid(row=0, column=0, sticky=(tk.W, tk.E, tk.N), pady=(0, 10))
        parent_frame.rowconfigure(0, weight=0)  # Don't expand
        parent_frame.rowconfigure(1, weight=1)  # Profiles panel expands
        parent_frame.columnconfigure(0, weight=1)

        # Toggle button (smaller)
        self.btn_monitor_toggle = ttk.Button(
            monitor_frame, text="Enable Monitor", command=self.toggle_monitor
        )
        self.btn_monitor_toggle.pack(pady=(0, 8))

        # Stats display with proper grid configuration
        stats_frame = ttk.Frame(monitor_frame)
        stats_frame.pack(fill=tk.BOTH, expand=True)

        # Configure grid columns for proper alignment
        stats_frame.columnconfigure(0, weight=0, minsize=70)  # Label column (fixed width)
        stats_frame.columnconfigure(1, weight=1)  # Value column (expands)

        # CPU
        ttk.Label(stats_frame, text="CPU:", font=("Segoe UI", 9, "bold")).grid(
            row=0, column=0, sticky=tk.W, pady=4
        )
        self.cpu_label = ttk.Label(
            stats_frame, text="--", font=("Consolas", 8), foreground=self.colors["info"]
        )
        self.cpu_label.grid(row=0, column=1, sticky=tk.W, padx=(5, 0))

        # Memory
        ttk.Label(stats_frame, text="RAM:", font=("Segoe UI", 9, "bold")).grid(
            row=1, column=0, sticky=tk.W, pady=4
        )
        self.mem_label = ttk.Label(
            stats_frame, text="--", font=("Consolas", 8), foreground=self.colors["info"]
        )
        self.mem_label.grid(row=1, column=1, sticky=tk.W, padx=(5, 0))

        # I/O Read
        ttk.Label(stats_frame, text="Net In:", font=("Segoe UI", 9, "bold")).grid(
            row=2, column=0, sticky=tk.W, pady=4
        )
        self.io_read_label = ttk.Label(
            stats_frame, text="--", font=("Consolas", 8), foreground=self.colors["info"]
        )
        self.io_read_label.grid(row=2, column=1, sticky=tk.W, padx=(5, 0))

        # I/O Write
        ttk.Label(stats_frame, text="Net Out:", font=("Segoe UI", 9, "bold")).grid(
            row=3, column=0, sticky=tk.W, pady=4
        )
        self.io_write_label = ttk.Label(
            stats_frame, text="--", font=("Consolas", 8), foreground=self.colors["info"]
        )
        self.io_write_label.grid(row=3, column=1, sticky=tk.W, padx=(5, 0))

        # GPU (if available)
        ttk.Label(stats_frame, text="GPU:", font=("Segoe UI", 9, "bold")).grid(
            row=4, column=0, sticky=tk.W, pady=4
        )
        self.gpu_label = ttk.Label(
            stats_frame, text="--", font=("Consolas", 8), foreground=self.colors["info"]
        )
        self.gpu_label.grid(row=4, column=1, sticky=tk.W, padx=(5, 0))

        # Status
        self.monitor_status = ttk.Label(
            monitor_frame, text="Monitor disabled", font=("Segoe UI", 8), foreground="gray"
        )
        self.monitor_status.pack(pady=(8, 0))

    def toggle_monitor(self):
        """Toggle resource monitoring on/off."""
        self._monitor_enabled = not self._monitor_enabled

        if self._monitor_enabled:
            self.btn_monitor_toggle.config(text="Disable Monitor")
            self.monitor_status.config(text="Monitoring active", foreground=self.colors["success"])
            self._update_resource_stats()
        else:
            self.btn_monitor_toggle.config(text="Enable Monitor")
            self.monitor_status.config(text="Monitor disabled", foreground="gray")
            if self._monitor_job:
                self.window.after_cancel(self._monitor_job)
                self._monitor_job = None
            # Reset labels
            self.cpu_label.config(text="--")
            self.mem_label.config(text="--")
            self.io_read_label.config(text="--")
            self.io_write_label.config(text="--")
            self.gpu_label.config(text="--")

    def _update_resource_stats(self):
        """Update resource statistics using container stats."""
        if not self._monitor_enabled:
            return

        try:
            import re
            import subprocess

            # Get container configuration
            config = self._gather_config()
            runtime = config.get("runtime", "podman")
            container_name = "tlauncher"

            try:
                # Get container stats (one-shot, no stream)
                result = subprocess.run(
                    [
                        runtime,
                        "stats",
                        "--no-stream",
                        "--format",
                        "json" if runtime == "podman" else "table",
                        container_name,
                    ],
                    capture_output=True,
                    text=True,
                    timeout=3,
                )

                if result.returncode == 0 and result.stdout.strip():
                    output = result.stdout.strip()

                    if runtime == "podman":
                        # Podman outputs JSON array with one object
                        import json

                        stats_list = json.loads(output)

                        # Get first (and only) container stats
                        if isinstance(stats_list, list) and len(stats_list) > 0:
                            stats = stats_list[0]
                        else:
                            stats = stats_list if isinstance(stats_list, dict) else {}

                        # CPU % (Podman uses 'cpu_percent' not 'CPU')
                        # Container stats show per-core usage, normalize to total system CPU
                        cpu_raw = stats.get("cpu_percent", "0%").replace("%", "")
                        try:
                            cpu_normalized = float(cpu_raw) / self._cpu_cores
                            cpu_cores = float(cpu_raw) / 100
                            self.cpu_label.config(
                                text=f"{cpu_normalized:.1f}%\n({cpu_cores:.1f} cores)"
                            )
                        except (ValueError, ZeroDivisionError):
                            self.cpu_label.config(text=f"{cpu_raw}%")

                        # Memory (Podman uses 'mem_usage' not 'MemUsage')
                        mem_usage = stats.get("mem_usage", "0B / 0B")
                        mem_parts = mem_usage.split("/")
                        if mem_parts:
                            self.mem_label.config(text=mem_parts[0].strip())

                        # Network I/O (Podman uses 'net_io' not 'NetIO')
                        net_io = stats.get("net_io", "0B / 0B")
                        net_parts = net_io.split("/")
                        if len(net_parts) == 2:
                            self.io_read_label.config(text=net_parts[0].strip())
                            self.io_write_label.config(text=net_parts[1].strip())

                    else:
                        # Docker outputs table format
                        # Parse the output line (skip header if present)
                        lines = output.split("\n")
                        data_line = lines[-1] if len(lines) > 0 else ""

                        # Format: CONTAINER ID   NAME   CPU %   MEM USAGE / LIMIT   MEM %   NET I/O   BLOCK I/O   PIDS
                        parts = re.split(r"\s{2,}", data_line.strip())

                        if len(parts) >= 3:
                            # CPU % (index 2)
                            # Container stats show per-core usage, normalize to total system CPU
                            cpu_raw = parts[2].replace("%", "")
                            try:
                                cpu_normalized = float(cpu_raw) / self._cpu_cores
                                cpu_cores = float(cpu_raw) / 100
                                self.cpu_label.config(
                                    text=f"{cpu_normalized:.1f}%\n({cpu_cores:.1f} cores)"
                                )
                            except (ValueError, ZeroDivisionError):
                                self.cpu_label.config(text=f"{cpu_raw}%")

                            # MEM USAGE (index 3)
                            if len(parts) >= 4:
                                mem_usage = parts[3].split("/")[0].strip()
                                self.mem_label.config(text=mem_usage)

                            # NET I/O (index 5)
                            if len(parts) >= 6:
                                net_io = parts[5]
                                net_parts = net_io.split("/")
                                if len(net_parts) == 2:
                                    self.io_read_label.config(text=net_parts[0].strip())
                                    self.io_write_label.config(text=net_parts[1].strip())

                    # GPU stats (NVIDIA only)
                    try:
                        if config.get("gpu") == "nvidia":
                            gpu_result = subprocess.run(
                                [
                                    "nvidia-smi",
                                    "--query-gpu=utilization.gpu",
                                    "--format=csv,noheader,nounits",
                                ],
                                capture_output=True,
                                text=True,
                                timeout=1,
                            )
                            if gpu_result.returncode == 0:
                                gpu_util = gpu_result.stdout.strip()
                                self.gpu_label.config(text=f"{gpu_util}%")
                            else:
                                self.gpu_label.config(text="--")
                        else:
                            self.gpu_label.config(text="N/A")
                    except (FileNotFoundError, subprocess.TimeoutExpired):
                        self.gpu_label.config(text="--")

                else:
                    # Container not running or not found
                    self._reset_monitor_labels()

            except (subprocess.TimeoutExpired, ValueError, json.JSONDecodeError):
                self._reset_monitor_labels()

        except Exception as e:
            self.log(f"Monitor error: {e}")

        # Schedule next update (2 seconds)
        if self._monitor_enabled:
            self._monitor_job = self.window.after(2000, self._update_resource_stats)

    def _reset_monitor_labels(self):
        """Reset monitor labels when container is not running."""
        self.cpu_label.config(text="--")
        self.mem_label.config(text="--")
        self.io_read_label.config(text="--")
        self.io_write_label.config(text="--")
        self.gpu_label.config(text="--")

    def _create_profiles_panel(self, parent_frame):
        """Create profiles management panel."""
        profiles_frame = ttk.LabelFrame(parent_frame, text="📦 Minecraft Profiles", padding="10")
        profiles_frame.grid(row=1, column=0, sticky=(tk.W, tk.E, tk.N, tk.S))

        # Buttons frame — 4 equal columns, fills full width
        btn_frame = ttk.Frame(profiles_frame)
        btn_frame.pack(fill=tk.X, pady=(0, 8))
        for _col in range(4):
            btn_frame.columnconfigure(_col, weight=1)

        btn_import = ttk.Button(btn_frame, text="📥 Import", command=self.import_profile)
        btn_import.grid(row=0, column=0, sticky=(tk.W, tk.E), padx=(0, 4))

        btn_refresh = ttk.Button(btn_frame, text="🔄 Refresh", command=self.refresh_profiles)
        btn_refresh.grid(row=0, column=1, sticky=(tk.W, tk.E), padx=4)

        btn_help = ttk.Button(btn_frame, text="?", command=self.show_profile_help)
        btn_help.grid(row=0, column=2, sticky=(tk.W, tk.E), padx=4)

        btn_info = ttk.Button(btn_frame, text="📋 Info", command=self.show_profile_info)
        btn_info.grid(row=0, column=3, sticky=(tk.W, tk.E), padx=(4, 0))

        # Profiles list with scrollbar
        list_frame = ttk.Frame(profiles_frame)
        list_frame.pack(fill=tk.BOTH, expand=True)

        scrollbar = ttk.Scrollbar(list_frame)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)

        self.profiles_listbox = tk.Listbox(
            list_frame,
            yscrollcommand=scrollbar.set,
            bg="#1e1e1e",
            fg="#d4d4d4",
            selectbackground="#7cbd3f",
            selectforeground="#1e1e1e",
            font=("Segoe UI", 9),
            height=8,
            relief=tk.FLAT,
            borderwidth=0,
        )
        self.profiles_listbox.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scrollbar.config(command=self.profiles_listbox.yview)

        # Right-click context menu
        self._profiles_ctx_menu = tk.Menu(
            self.window,
            tearoff=0,
            bg="#2d2d2d",
            fg="#d4d4d4",
            activebackground="#7cbd3f",
            activeforeground="#1e1e1e",
            bd=0,
        )
        self._profiles_ctx_menu.add_command(label="📋 Info", command=self.show_profile_info)
        self._profiles_ctx_menu.add_command(
            label="📁 Open Folder", command=self.open_profile_folder
        )
        self._profiles_ctx_menu.add_command(label="📤 Export", command=self.export_profile)
        self._profiles_ctx_menu.add_separator()
        self._profiles_ctx_menu.add_command(label="📥 Import", command=self.import_profile)
        self._profiles_ctx_menu.add_command(label="🔄 Refresh", command=self.refresh_profiles)
        self._profiles_ctx_menu.add_separator()
        self._profiles_ctx_menu.add_command(label="🗑 Delete", command=self.delete_profile)
        self.profiles_listbox.bind("<Button-3>", self._show_profiles_context_menu)

        # Profile action buttons — 3 equal columns, fills full width
        action_frame = ttk.Frame(profiles_frame)
        action_frame.pack(fill=tk.X, pady=(8, 0))
        for _col in range(3):
            action_frame.columnconfigure(_col, weight=1)

        btn_export = ttk.Button(action_frame, text="📤 Export", command=self.export_profile)
        btn_export.grid(row=0, column=0, sticky=(tk.W, tk.E), padx=(0, 4))

        btn_open_folder = ttk.Button(
            action_frame, text="📁 Open Folder", command=self.open_profile_folder
        )
        btn_open_folder.grid(row=0, column=1, sticky=(tk.W, tk.E), padx=4)

        btn_delete = ttk.Button(action_frame, text="🗑 Delete", command=self.delete_profile)
        btn_delete.grid(row=0, column=2, sticky=(tk.W, tk.E), padx=(4, 0))

        # Load profiles
        self.refresh_profiles()

    def refresh_profiles(self):
        """Refresh the profiles list."""
        import json
        from pathlib import Path

        self.profiles_listbox.delete(0, tk.END)

        try:
            # Read launcher_profiles.json
            profiles_file = Path(__file__).parent / "home" / "launcher_profiles.json"
            if not profiles_file.exists():
                self.profiles_listbox.insert(tk.END, "(No profiles found)")
                return

            with open(profiles_file) as f:
                data = json.load(f)

            profiles = data.get("profiles", {})
            if not profiles:
                self.profiles_listbox.insert(tk.END, "(No profiles found)")
                return

            # Add profiles to list
            for profile_id, profile_data in profiles.items():
                name = profile_data.get("name", profile_id)
                version = profile_data.get("lastVersionId", "unknown")
                profile_type = profile_data.get("type", "custom")

                # Format: "MC02 (v1.21) [custom]"
                display_text = f"{name} (v{version}) [{profile_type}]"
                self.profiles_listbox.insert(tk.END, display_text)

                # Store profile ID as metadata
                self.profiles_listbox.itemconfig(
                    tk.END,
                    fg="#7cbd3f"
                    if profile_data.get("name") == data.get("selectedProfile")
                    else "#d4d4d4",
                )

        except Exception as e:
            self.log(f"Error loading profiles: {e}")
            self.profiles_listbox.insert(tk.END, f"(Error: {e})")

    def export_profile(self):
        """Export selected profile to ZIP file."""
        import json
        import zipfile
        from pathlib import Path
        from tkinter import filedialog, messagebox

        # Get selected profile
        selection = self.profiles_listbox.curselection()
        if not selection:
            messagebox.showwarning("No Selection", "Please select a profile to export.")
            return

        try:
            # Read launcher_profiles.json
            profiles_file = Path(__file__).parent / "home" / "launcher_profiles.json"
            with open(profiles_file) as f:
                data = json.load(f)

            profiles = data.get("profiles", {})
            profile_keys = list(profiles.keys())
            selected_idx = selection[0]

            if selected_idx >= len(profile_keys):
                messagebox.showerror("Error", "Invalid profile selection.")
                return

            profile_id = profile_keys[selected_idx]
            profile_data = profiles[profile_id]
            profile_name = profile_data.get("name", profile_id)
            version_id = profile_data.get("lastVersionId", "unknown")

            # Ask where to save
            default_filename = f"{profile_name}_{version_id}.mcprofile.zip"
            save_path = filedialog.asksaveasfilename(
                defaultextension=".zip",
                initialfile=default_filename,
                filetypes=[("Minecraft Profile", "*.mcprofile.zip"), ("ZIP files", "*.zip")],
            )

            if not save_path:
                return

            self.log(f"\n📤 Exporting profile: {profile_name}")

            # Create ZIP file
            with zipfile.ZipFile(save_path, "w", zipfile.ZIP_DEFLATED) as zipf:
                # Add metadata
                metadata = {
                    "profile_id": profile_id,
                    "profile_data": profile_data,
                    "version_id": version_id,
                    "export_version": "1.0",
                }
                zipf.writestr("profile_metadata.json", json.dumps(metadata, indent=2))

                # Add version files from home/versions/[version_id]/
                version_dir = Path(__file__).parent / "home" / "versions" / version_id
                if version_dir.exists():
                    for file_path in version_dir.rglob("*"):
                        if file_path.is_file():
                            arcname = f"version/{file_path.relative_to(version_dir)}"
                            zipf.write(file_path, arcname)
                            self.log(f"  + {arcname}")

                # Add game data if custom gameDir
                game_dir = profile_data.get("gameDir")
                if game_dir and not game_dir.startswith("/home/app/.minecraft/versions"):
                    # Custom game directory - try to export it
                    # gameDir is container path, convert to host path
                    # /home/app/.minecraft/foo -> home/foo
                    if game_dir.startswith("/home/app/.minecraft/"):
                        relative_path = game_dir.replace("/home/app/.minecraft/", "")
                        host_game_dir = Path(__file__).parent / "home" / relative_path

                        if host_game_dir.exists():
                            for file_path in host_game_dir.rglob("*"):
                                if file_path.is_file():
                                    arcname = f"gamedata/{file_path.relative_to(host_game_dir)}"
                                    zipf.write(file_path, arcname)

            self.log(f"✓ Profile exported to: {save_path}")
            messagebox.showinfo(
                "Export Complete", f"Profile exported successfully to:\n{save_path}"
            )

        except Exception as e:
            self.log(f"✗ Export failed: {e}")
            messagebox.showerror("Export Failed", f"Failed to export profile:\n{e}")

    def import_profile(self):
        """Import profile from ZIP file."""
        import json
        import zipfile
        from pathlib import Path
        from tkinter import filedialog, messagebox

        # Ask for ZIP file
        zip_path = filedialog.askopenfilename(
            title="Select Profile to Import",
            filetypes=[
                ("Minecraft Profile", "*.mcprofile.zip"),
                ("ZIP files", "*.zip"),
                ("All files", "*.*"),
            ],
        )

        if not zip_path:
            return

        try:
            self.log(f"\n📥 Importing profile from: {Path(zip_path).name}")

            with zipfile.ZipFile(zip_path, "r") as zipf:
                # Read metadata
                if "profile_metadata.json" not in zipf.namelist():
                    messagebox.showerror(
                        "Invalid Archive",
                        "This is not a valid Minecraft profile archive.\nMissing profile_metadata.json",
                    )
                    return

                metadata_content = zipf.read("profile_metadata.json").decode("utf-8")
                metadata = json.loads(metadata_content)

                profile_data = metadata.get("profile_data", {})
                version_id = metadata.get("version_id", "unknown")
                profile_name = profile_data.get("name", "Imported Profile")

                self.log(f"  Profile: {profile_name}")
                self.log(f"  Version: {version_id}")

                # Extract version files
                version_dir = Path(__file__).parent / "home" / "versions" / version_id
                version_dir.mkdir(parents=True, exist_ok=True)

                for item in zipf.namelist():
                    if item.startswith("version/"):
                        target_path = version_dir / item.replace("version/", "")
                        target_path.parent.mkdir(parents=True, exist_ok=True)

                        with zipf.open(item) as source, open(target_path, "wb") as target:
                            target.write(source.read())
                        self.log(f"  + {item}")

                # Extract game data if present
                has_gamedata = any(item.startswith("gamedata/") for item in zipf.namelist())
                if has_gamedata:
                    game_dir = version_dir  # Place in same directory by default
                    for item in zipf.namelist():
                        if item.startswith("gamedata/"):
                            target_path = game_dir / item.replace("gamedata/", "")
                            target_path.parent.mkdir(parents=True, exist_ok=True)

                            with zipf.open(item) as source, open(target_path, "wb") as target:
                                target.write(source.read())

                # Update launcher_profiles.json
                profiles_file = Path(__file__).parent / "home" / "launcher_profiles.json"

                if profiles_file.exists():
                    with open(profiles_file) as f:
                        launcher_data = json.load(f)
                else:
                    launcher_data = {"clientToken": "imported", "profiles": {}}

                # Generate unique profile ID if needed
                base_id = profile_data.get("name", version_id).replace(" ", "_")
                profile_id = base_id
                counter = 1
                while profile_id in launcher_data.get("profiles", {}):
                    profile_id = f"{base_id}_{counter}"
                    counter += 1

                # Add profile
                new_profile = {
                    "name": profile_data.get("name", version_id),
                    "type": profile_data.get("type", "custom"),
                    "created": profile_data.get("created", "2024-01-01T00:00:00.000Z"),
                    "lastUsed": profile_data.get("lastUsed", "2024-01-01T00:00:00.000Z"),
                    "lastVersionId": version_id,
                }

                # Add gameDir if it was custom
                if profile_data.get("gameDir"):
                    new_profile["gameDir"] = f"/home/app/.minecraft/versions/{version_id}"

                launcher_data.setdefault("profiles", {})[profile_id] = new_profile

                # Save
                with open(profiles_file, "w") as f:
                    json.dump(launcher_data, f, indent=2)

            self.log("✓ Profile imported successfully!")
            messagebox.showinfo(
                "Import Complete", f"Profile '{profile_name}' imported successfully!"
            )

            # Refresh profiles list
            self.refresh_profiles()

        except Exception as e:
            self.log(f"✗ Import failed: {e}")
            messagebox.showerror("Import Failed", f"Failed to import profile:\n{e}")

    def delete_profile(self):
        """Delete selected profile."""
        import json
        from pathlib import Path
        from tkinter import messagebox

        # Get selected profile
        selection = self.profiles_listbox.curselection()
        if not selection:
            messagebox.showwarning("No Selection", "Please select a profile to delete.")
            return

        try:
            # Read launcher_profiles.json
            profiles_file = Path(__file__).parent / "home" / "launcher_profiles.json"
            with open(profiles_file) as f:
                data = json.load(f)

            profiles = data.get("profiles", {})
            profile_keys = list(profiles.keys())
            selected_idx = selection[0]

            if selected_idx >= len(profile_keys):
                messagebox.showerror("Error", "Invalid profile selection.")
                return

            profile_id = profile_keys[selected_idx]
            profile_data = profiles[profile_id]
            profile_name = profile_data.get("name", profile_id)

            # Confirm deletion
            confirm = messagebox.askyesno(
                "Confirm Deletion",
                f"Delete profile '{profile_name}'?\n\n"
                f"This will remove the profile entry from TLauncher.\n"
                f"Version files will NOT be deleted.",
            )

            if not confirm:
                return

            # Remove from profiles
            del profiles[profile_id]

            # Update selected profile if needed
            if data.get("selectedProfile") == profile_id:
                # Select first remaining profile or None
                if profiles:
                    data["selectedProfile"] = list(profiles.keys())[0]
                else:
                    data["selectedProfile"] = None

            # Save
            with open(profiles_file, "w") as f:
                json.dump(data, f, indent=2)

            self.log(f"\n🗑 Deleted profile: {profile_name}")
            messagebox.showinfo("Profile Deleted", f"Profile '{profile_name}' has been deleted.")

            # Refresh list
            self.refresh_profiles()

        except Exception as e:
            self.log(f"✗ Delete failed: {e}")
            messagebox.showerror("Delete Failed", f"Failed to delete profile:\n{e}")

    def _show_profiles_context_menu(self, event):
        """Select the item under the cursor and show the right-click context menu."""
        idx = self.profiles_listbox.nearest(event.y)
        if idx >= 0:
            self.profiles_listbox.selection_clear(0, tk.END)
            self.profiles_listbox.selection_set(idx)
            self.profiles_listbox.activate(idx)
        try:
            self._profiles_ctx_menu.tk_popup(event.x_root, event.y_root)
        finally:
            self._profiles_ctx_menu.grab_release()

    def open_profile_folder(self):
        """Open the selected profile's version folder in the file manager."""
        import json
        import subprocess
        from pathlib import Path
        from tkinter import messagebox

        selection = self.profiles_listbox.curselection()
        if not selection:
            messagebox.showwarning("No Selection", "Please select a profile to open its folder.")
            return

        try:
            profiles_file = Path(__file__).parent / "home" / "launcher_profiles.json"
            with open(profiles_file) as f:
                data = json.load(f)

            profiles = data.get("profiles", {})
            profile_keys = list(profiles.keys())
            selected_idx = selection[0]

            if selected_idx >= len(profile_keys):
                messagebox.showerror("Error", "Invalid profile selection.")
                return

            profile_data = profiles[profile_keys[selected_idx]]
            version_id = profile_data.get("lastVersionId", "unknown")

            folder = Path(__file__).parent / "home" / "versions" / version_id
            folder.mkdir(parents=True, exist_ok=True)

            subprocess.Popen(["xdg-open", str(folder)])

        except Exception as e:
            messagebox.showerror("Error", f"Could not open folder:\n{e}")

    def show_profile_help(self):
        """Show a help dialog explaining import/export and manual import."""
        import tkinter as tk
        from tkinter import ttk

        win = tk.Toplevel(self.window)
        win.title("Profile Import & Export Help")
        win.resizable(True, True)
        win.configure(bg="#1e1e1e")
        win.minsize(560, 400)

        text = (
            "EXPORT\n"
            "──────\n"
            "Select a profile and click Export. A .mcprofile.zip file is saved to a\n"
            "location you choose. It contains:\n"
            "  • profile_metadata.json  — profile name, version, settings\n"
            "  • version/               — all version JAR and asset files\n"
            "  • gamedata/              — custom game directory files (if any)\n\n"
            "IMPORT\n"
            "──────\n"
            "Click Import and select a .mcprofile.zip file. The launcher will:\n"
            "  1. Extract version files into the launcher's versions directory\n"
            "  2. Add a new entry to launcher_profiles.json\n"
            "  3. If the profile name already exists a numeric suffix is appended\n\n"
            "MANUAL IMPORT\n"
            "─────────────\n"
            "If you have version files but no .mcprofile.zip:\n\n"
            "  1. Copy the version folder into the launcher's versions directory:\n"
            "       Linux:   <launcher-dir>/home/versions/<version>/\n"
            "       Windows: <launcher-dir>\\home\\versions\\<version>\\\n"
            "     (must contain the .jar and .json for that version)\n\n"
            "  2. Open the profiles file in a text editor:\n"
            "       Linux:   <launcher-dir>/home/launcher_profiles.json\n"
            "       Windows: <launcher-dir>\\home\\launcher_profiles.json\n\n"
            '  3. Add an entry under "profiles":\n'
            '       "MyProfile": {\n'
            '         "name": "MyProfile",\n'
            '         "type": "custom",\n'
            '         "lastVersionId": "<version>",\n'
            '         "created": "2024-01-01T00:00:00.000Z",\n'
            '         "lastUsed":  "2024-01-01T00:00:00.000Z"\n'
            "       }\n\n"
            "  4. Click Refresh in the launcher."
        )

        frame = ttk.Frame(win, padding=16)
        frame.pack(fill=tk.BOTH, expand=True)

        lbl = tk.Label(
            frame,
            text=text,
            justify=tk.LEFT,
            bg="#1e1e1e",
            fg="#d4d4d4",
            font=("Courier New", 9),
            anchor="w",
        )
        lbl.pack(anchor="w", fill=tk.X)

        ttk.Button(frame, text="Close", command=win.destroy, width=10).pack(
            anchor="e", pady=(12, 0)
        )

        win.update_idletasks()
        x = self.window.winfo_x() + (self.window.winfo_width() - win.winfo_width()) // 2
        y = self.window.winfo_y() + (self.window.winfo_height() - win.winfo_height()) // 2
        win.geometry(f"+{x}+{y}")

    def show_profile_info(self):
        """Show detailed info for the selected profile."""
        import json
        import re
        import tkinter as tk
        from pathlib import Path
        from tkinter import messagebox, ttk

        selection = self.profiles_listbox.curselection()
        if not selection:
            messagebox.showwarning("No Selection", "Please select a profile to view its info.")
            return

        try:
            profiles_file = Path(__file__).parent / "home" / "launcher_profiles.json"
            with open(profiles_file) as f:
                data = json.load(f)

            profiles = data.get("profiles", {})
            profile_keys = list(profiles.keys())
            selected_idx = selection[0]
            if selected_idx >= len(profile_keys):
                messagebox.showerror("Error", "Invalid profile selection.")
                return

            profile_id = profile_keys[selected_idx]
            profile_data = profiles[profile_id]
            profile_name = profile_data.get("name", profile_id)
            version_id = profile_data.get("lastVersionId", "unknown")
            profile_type = profile_data.get("type", "custom")
            game_dir = profile_data.get("gameDir", "")

            version_dir = Path(__file__).parent / "home" / "versions" / version_id

            # Parse version JSON for modloader and Java version
            modloader = "Vanilla"
            modloader_version = ""
            java_version = "?"
            mc_version = version_id

            version_json = version_dir / f"{version_id}.json"
            if version_json.exists():
                with open(version_json) as f:
                    vdata = json.load(f)
                java_version = str(vdata.get("javaVersion", {}).get("majorVersion", "?"))
                libs = [lib["name"] for lib in vdata.get("libraries", [])]
                if any("neoforged" in lib for lib in libs):
                    modloader = "NeoForge"
                elif any("net.minecraftforge:forge:" in lib for lib in libs):
                    modloader = "Forge"
                elif any("net.fabricmc:fabric-loader:" in lib for lib in libs):
                    modloader = "Fabric"
                elif any("org.quiltmc:quilt-loader:" in lib for lib in libs):
                    modloader = "Quilt"

            # Refine MC version and modloader version from TLauncherAdditional.json
            tl_additional = version_dir / "TLauncherAdditional.json"
            if tl_additional.exists():
                with open(tl_additional) as f:
                    tl_data = json.load(f)
                paths = [x["path"] for x in tl_data.get("additionalFiles", [])]
                for p in paths:
                    m = re.search(r"net/minecraft/client/(\d+\.\d+[\.\d]*)", p)
                    if m:
                        mc_version = m.group(1)
                        break
                patterns = {
                    "NeoForge": r"net/neoforged/neoforge/([^/]+)",
                    "Forge": r"net/minecraftforge/forge/([^/]+)",
                    "Fabric": r"net/fabricmc/fabric-loader/([^/]+)",
                    "Quilt": r"org/quiltmc/quilt-loader/([^/]+)",
                }
                if modloader in patterns:
                    for p in paths:
                        m = re.search(patterns[modloader], p)
                        if m:
                            modloader_version = m.group(1)
                            break

            # Resolve mods directory on host
            if game_dir.startswith("/home/app/.minecraft/"):
                rel = game_dir.replace("/home/app/.minecraft/", "")
                mods_dir = Path(__file__).parent / "home" / rel / "mods"
            else:
                mods_dir = Path(__file__).parent / "home" / "mods"

            active_mods = []
            disabled_mods = []
            if mods_dir.exists():
                for entry in sorted(mods_dir.iterdir()):
                    name = entry.name
                    if name.endswith(".jar.deactivation"):
                        disabled_mods.append(name[: -len(".deactivation")])
                    elif name.endswith(".jar"):
                        active_mods.append(name)

            # Build info window
            win = tk.Toplevel(self.window)
            win.title(f"Profile Info — {profile_name}")
            win.resizable(True, True)
            win.minsize(480, 300)
            win.configure(bg="#1e1e1e")

            frame = ttk.Frame(win, padding=16)
            frame.pack(fill=tk.BOTH, expand=True)

            def info_row(label, value, value_fg="#d4d4d4"):
                r = ttk.Frame(frame)
                r.pack(fill=tk.X, pady=1)
                tk.Label(
                    r,
                    text=f"{label:<18}",
                    bg="#1e1e1e",
                    fg="#888888",
                    font=("Courier New", 9),
                    anchor="w",
                ).pack(side=tk.LEFT)
                tk.Label(
                    r,
                    text=value,
                    bg="#1e1e1e",
                    fg=value_fg,
                    font=("Courier New", 9, "bold"),
                    anchor="w",
                ).pack(side=tk.LEFT)

            info_row("Profile", profile_name)
            info_row("Type", profile_type)
            info_row("MC Version", mc_version, "#7cbd3f")
            ml_label = f"{modloader} {modloader_version}".strip()
            info_row("Modloader", ml_label, "#7cbd3f" if modloader != "Vanilla" else "#d4d4d4")
            info_row("Java", f"Java {java_version}")
            info_row("Version ID", version_id)

            ttk.Separator(frame, orient="horizontal").pack(fill=tk.X, pady=(8, 6))

            total = len(active_mods) + len(disabled_mods)
            info_row("Mods total", str(total))
            info_row("  Active", str(len(active_mods)), "#7cbd3f")
            info_row(
                "  Disabled",
                str(len(disabled_mods)),
                "#e57373" if disabled_mods else "#d4d4d4",
            )

            if active_mods or disabled_mods:
                ttk.Separator(frame, orient="horizontal").pack(fill=tk.X, pady=(8, 4))
                tk.Label(
                    frame,
                    text="Mods:",
                    bg="#1e1e1e",
                    fg="#888888",
                    font=("Courier New", 9),
                    anchor="w",
                ).pack(fill=tk.X)

                mod_list_frame = ttk.Frame(frame)
                mod_list_frame.pack(fill=tk.BOTH, expand=True, pady=(4, 0))

                sb = ttk.Scrollbar(mod_list_frame)
                sb.pack(side=tk.RIGHT, fill=tk.Y)

                lb = tk.Listbox(
                    mod_list_frame,
                    yscrollcommand=sb.set,
                    bg="#252525",
                    fg="#d4d4d4",
                    font=("Courier New", 8),
                    height=min(14, total),
                    relief=tk.FLAT,
                    borderwidth=0,
                    selectbackground="#333333",
                )
                lb.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
                sb.config(command=lb.yview)

                for name in active_mods:
                    lb.insert(tk.END, f"  ✓  {name}")
                    lb.itemconfig(tk.END, fg="#7cbd3f")
                for name in disabled_mods:
                    lb.insert(tk.END, f"  ✗  {name}")
                    lb.itemconfig(tk.END, fg="#888888")

            ttk.Button(frame, text="Close", command=win.destroy, width=10).pack(
                anchor="e", pady=(12, 0)
            )

            win.update_idletasks()
            x = self.window.winfo_x() + (self.window.winfo_width() - win.winfo_width()) // 2
            y = self.window.winfo_y() + (self.window.winfo_height() - win.winfo_height()) // 2
            win.geometry(f"+{x}+{y}")

        except Exception as e:
            messagebox.showerror("Error", f"Could not load profile info:\n{e}")

    def _poll_service_status(self):
        """Check podman.socket and docker service status, then reschedule."""
        import subprocess

        def _active(cmd):
            try:
                return subprocess.run(cmd, capture_output=True, timeout=3).returncode == 0
            except Exception:
                return False

        podman_up = _active(["systemctl", "--user", "is-active", "podman.socket"]) or _active(
            ["systemctl", "is-active", "podman.socket"]
        )
        docker_up = _active(["systemctl", "is-active", "docker"])

        def _apply():
            ok = self.colors["success"]
            off = "#555555"
            self.podman_svc_label.config(foreground=ok if podman_up else off)
            self.docker_svc_label.config(foreground=ok if docker_up else off)
            self._svc_poll_job = self.window.after(8000, self._schedule_service_poll)

        self.window.after(0, _apply)

    def _schedule_service_poll(self):
        threading.Thread(target=self._poll_service_status, daemon=True).start()

    def _check_for_updates_async(self):
        """Background thread: compare local HEAD SHA with remote and surface a banner if behind."""
        import subprocess

        repo = str(Path(__file__).parent)
        try:
            local = subprocess.run(
                ["git", "rev-parse", "HEAD"],
                capture_output=True,
                text=True,
                cwd=repo,
                timeout=5,
            )
            remote = subprocess.run(
                ["git", "ls-remote", "origin", "HEAD"],
                capture_output=True,
                text=True,
                cwd=repo,
                timeout=15,
            )
            local_sha = local.stdout.strip()
            remote_sha = (
                remote.stdout.split()[0] if remote.returncode == 0 and remote.stdout else ""
            )
            if local_sha and remote_sha and local_sha != remote_sha:
                self.window.after(0, lambda: self._show_update_banner(remote_sha))
        except Exception:
            pass

    def _show_update_banner(self, remote_sha: str):
        """Show the update notification in the status bar (called on the main thread)."""
        short = remote_sha[:7]
        self._update_label.config(text=f"⬆ Update available ({short})")
        self._update_frame.pack(side=tk.LEFT, padx=(16, 0))
        self.log(f"\n⬆ Update available — remote HEAD is {short}")

    def _do_update(self):
        """Pull latest changes from origin on a background thread."""
        import subprocess

        confirm = messagebox.askyesno(
            "Update Launcher",
            "Pull the latest changes from GitHub?\n\n"
            "The launcher will update but you must restart it manually afterwards.",
        )
        if not confirm:
            return

        self.log("\n⬆ Pulling latest changes from origin…")

        def _pull():
            result = subprocess.run(
                ["git", "pull"],
                capture_output=True,
                text=True,
                cwd=str(Path(__file__).parent),
            )

            def _on_done():
                if result.returncode == 0:
                    self.log(result.stdout.strip())
                    self.log("✓ Update complete — please restart the launcher")
                    self._update_frame.pack_forget()
                    messagebox.showinfo(
                        "Update Complete",
                        "Launcher updated successfully.\n\nPlease restart the launcher.",
                    )
                else:
                    self.log(f"✗ git pull failed:\n{result.stderr.strip()}")
                    messagebox.showerror(
                        "Update Failed", f"git pull returned an error:\n\n{result.stderr.strip()}"
                    )

            self.window.after(0, _on_done)

        threading.Thread(target=_pull, daemon=True).start()

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

    def _check_existing_container(self):
        """Check if the container is already running and update UI accordingly."""
        try:
            import subprocess

            runtime = self.detected.get("runtime", "podman")
            container_name = "tlauncher"

            # Check container status
            result = subprocess.run(
                [runtime, "ps", "--filter", f"name={container_name}", "--format", "{{.Names}}"],
                capture_output=True,
                text=True,
                timeout=3,
            )

            if result.returncode == 0 and container_name in result.stdout:
                # Container is already running
                self.log("\n⚠️  Detected existing Minecraft instance!")
                self.log("Container is already running.")
                self._update_status("Already Running", "warning")

                # Disable start button, enable stop button
                self.btn_start.config(state="disabled")
                self.btn_stop.config(state="normal")
                self.btn_restart.config(state="normal")

                # Create manager instance for the running container
                self.manager = ContainerManager(self.config)
            else:
                # Container not running
                self.log("\n🚀 Ready to start!")
                self._update_status("Ready", "success")

        except Exception:
            # If check fails, assume not running
            self.log("\n🚀 Ready to start!")
            self._update_status("Ready", "success")

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
            "auto_xhost": True,
        }

    def start_minecraft(self):
        """Start button handler."""
        # Check if already running
        try:
            import subprocess

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

        if not valid:
            self.log("\n✗ Validation failed. Cannot start.")
            self._update_status("Validation failed", "error")
            messagebox.showerror(
                "Validation Failed", "System validation failed. Check the output for details."
            )
            return

        self.log("✓ Validation passed")

        # Run xhost if needed
        if config["display"] == "x11" and config.get("auto_xhost", True):
            self.log("Setting X11 permissions...")
            if run_xhost_if_needed(config):
                self.log("✓ X11 permissions set")
            else:
                self.log("⚠ Could not set X11 permissions automatically")

        # Show command
        self.log(f"\nCommand: {get_command_preview(config, 'up')}\n")

        # Update UI state
        self._update_status("Starting...", "warning")
        self.btn_start.config(state=tk.DISABLED)
        self.btn_doctor.config(state=tk.DISABLED)

        # Start container in background thread
        def output_callback(line):
            self.log(line)

        def started_callback():
            # Launcher GUI is up; run UI update on main thread
            def _on_started():
                self._update_status("Running", "success")
                self.btn_stop.config(state=tk.NORMAL)
                self.btn_restart.config(state=tk.NORMAL)
                self.log("\n✓ Container started successfully")

            self.window.after(0, _on_started)

        def completion_callback(success):
            # Container process exited; run UI update on main thread
            def _on_exited():
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
                    if messagebox.askyesno(
                        "Minecraft stopped", "Minecraft exited unexpectedly.\n\nRestart?"
                    ):
                        self.start_minecraft()

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
        self.log("\n" + "=" * 50)
        self.log("Stopping container...")
        self._update_status("Stopping...", "warning")

        def stop_worker():
            manager = ContainerManager(config)
            success = manager.stop()

            def _on_stop_done():
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
        """Restart button handler."""
        config = self._gather_config()

        self.log("\n" + "=" * 50)
        self.log("Restarting container...")
        self._update_status("Restarting...", "warning")

        def restart_worker():
            manager = ContainerManager(config)

            def output_callback(line):
                self.log(line)

            success = manager.restart(output_callback=output_callback)

            if success:
                self._update_status("Running", "success")
                self.log("\n✓ Container restarted")
            else:
                self._update_status("Failed", "error")
                self.log("\n✗ Failed to restart container")

        threading.Thread(target=restart_worker, daemon=True).start()

    def rebuild_image(self):
        """Rebuild the container image using the configured runtime."""
        import subprocess

        config = self._gather_config()
        runtime = config.get("runtime", "podman")
        repo_dir = str(Path(__file__).parent)

        self.log(f"\n{'=' * 50}")
        self.log(f"🔨 Rebuilding container image with {runtime}...")
        self.log("This may take several minutes on the first run.\n")

        self.btn_rebuild.config(state=tk.DISABLED)
        self.btn_start.config(state=tk.DISABLED)

        def _build():
            try:
                proc = subprocess.Popen(
                    [runtime, "build", "--pull", "-t", "tlauncher-java", "."],
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

    def run_doctor(self):
        """Doctor button handler - run validation."""
        self.log("\n" + "=" * 50)
        self.log("Running system diagnostics...\n")

        details = get_detection_details()

        # Show detection details
        rt = details["runtime"]
        self.log(f"Runtime: {rt['value']} ({rt['path']})")

        gpu = details["gpu"]
        self.log(f"GPU: {gpu['details']}")

        disp = details["display"]
        self.log(f"Display: {disp['value']} (session: {disp['session_type']})")

        aud = details["audio"]
        self.log(f"Audio: {aud['details']}")

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

        if valid:
            self.log("\n✓ System ready!")
            messagebox.showinfo("System Check", "System is ready to run Minecraft!")
        else:
            self.log("\n✗ System has errors")
            messagebox.showwarning(
                "System Check", "System has validation errors. Check the output for details."
            )

    def save_configuration(self):
        """Save current configuration."""
        config = self._gather_config()

        # Save with 'auto' converted to empty strings
        save_data = {
            "runtime": "" if self.runtime_var.get() == "auto" else config["runtime"],
            "gpu": "" if self.gpu_var.get() == "auto" else config["gpu"],
            "display": "" if self.display_var.get() == "auto" else config["display"],
            "audio": "" if self.audio_var.get() == "auto" else config["audio"],
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
        import os
        import subprocess
        from pathlib import Path

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
        self.log_text.insert(tk.END, message + "\n")
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
