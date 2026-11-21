"""Main window layout: header, configuration dropdowns, controls, status, console."""

import tkinter as tk
from tkinter import scrolledtext, ttk

from core.config import DEFAULT_JAVA, DEFAULT_MEMORY, JAVA_VERSIONS, MEMORY_LIMITS
from ui.base import GUIBase
from ui.common import APP_BUILD


class LayoutMixin(GUIBase):
    """Builds the main window widgets; the right column comes from the monitor and profiles mixins."""

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
            text=f"v{APP_BUILD}",
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

        # Tray icon setting lives in the Settings dialog; the variable stays here
        self.tray_var = tk.BooleanVar(value=False)

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

        self.btn_settings = ttk.Button(
            control_frame, text="⚙  Settings", command=self.open_settings_dialog
        )
        self.btn_settings.grid(row=1, column=2, sticky=(tk.W, tk.E), padx=(4, 0))

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
