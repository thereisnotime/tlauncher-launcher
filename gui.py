"""
GUI interface for Minecraft Launcher.
Provides graphical Tkinter-based interaction.
"""

import json
import os
import platform
import re
import subprocess
import threading
import time
import tkinter as tk
import urllib.parse
import webbrowser
from pathlib import Path
from tkinter import filedialog, messagebox, scrolledtext, simpledialog, ttk
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
from core.packs import PackError, import_archive
from core.validator import COMPOSE_V2_MISSING, run_xhost_if_needed, validate_system
from ui.common import APP_DIR, APP_VERSION
from ui.monitor import ResourceMonitorMixin
from ui.profiles import ProfilesMixin
from ui.theme import ThemeMixin

__all__ = ["APP_VERSION", "MinecraftLauncherGUI"]


class MinecraftLauncherGUI(ThemeMixin, ResourceMonitorMixin, ProfilesMixin):
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

    def import_profile(self):
        """Import a modpack/profile/mods zip from a local file (file picker)."""

        path = filedialog.askopenfilename(
            title="Select a modpack, profile or mods zip",
            filetypes=[
                ("Modpacks and profiles", "*.mrpack *.zip"),
                ("Modrinth modpack", "*.mrpack"),
                ("ZIP files", "*.zip"),
                ("All files", "*.*"),
            ],
        )
        if path:
            self._start_import(path)

    def import_profile_from_url(self):
        """Import from a URL: paste the link, OK, done."""

        url = simpledialog.askstring(
            "Import from URL",
            "Paste a link to a .mrpack modpack, a mods .zip or a .mcprofile.zip.\n"
            "Google Drive, Dropbox and GitHub share links work too.",
            parent=self.window,
        )
        if not url:
            return
        url = url.strip()
        if not url.lower().startswith(("http://", "https://")):
            messagebox.showerror("Invalid URL", "Please enter an http:// or https:// URL.")
            return
        self._start_import(url)

    def _start_import(self, source: str):
        """Run an import in a background thread, logging progress to the GUI."""

        if getattr(self, "_import_running", False):
            messagebox.showinfo("Import running", "An import is already in progress.")
            return
        self._import_running = True
        config = self._gather_config()
        runtime, java = config.get("runtime", "podman"), config["java"]

        def log(msg):
            self.window.after(0, lambda m=msg: self.log(m))

        def choose_target(versions):
            # Plain mods zip: ask on the main thread which version gets the mods.
            done = threading.Event()
            box = {}

            def ask():
                box["v"] = self._ask_mods_target(versions)
                done.set()

            self.window.after(0, ask)
            done.wait()
            return box.get("v")

        def worker():
            try:
                if not image_exists(runtime, java):
                    # Needed for Forge/NeoForge installers; same image as Start.
                    log(f"Building {image_tag(java)} first (one time)...")
                    proc = subprocess.Popen(
                        build_image_command(runtime, java),
                        stdout=subprocess.PIPE,
                        stderr=subprocess.STDOUT,
                        text=True,
                        cwd=str(APP_DIR),
                    )
                    for line in proc.stdout:
                        log(line.rstrip())
                    if proc.wait() != 0:
                        raise PackError("Image build failed")
                result = import_archive(
                    source,
                    runtime=runtime,
                    image=image_tag(java),
                    log=log,
                    choose_target=choose_target,
                )
            except Exception as e:  # noqa: BLE001 (surface every failure to the user)
                err = str(e)
                self.window.after(0, lambda: self._import_finished(None, err))
                return
            self.window.after(0, lambda: self._import_finished(result, None))

        self.log(f"\n{'=' * 50}\n📥 Importing {source}")
        threading.Thread(target=worker, daemon=True).start()

    def _import_finished(self, result, error):
        self._import_running = False
        if error:
            self.log(f"✗ Import failed: {error}")
            if error != "Import cancelled":
                messagebox.showerror("Import Failed", error)
            return
        self.log(f"✓ Imported {result.name} ({result.files} files)")
        self.refresh_profiles()
        if result.kind == "mrpack":
            msg = (
                f"{result.name} is installed.\n\n"
                f"Start the launcher, pick {result.version_id} in TLauncher and play."
            )
        elif result.kind == "mods":
            where = result.version_id or "the shared mods folder"
            msg = f"Installed {result.files} file(s) into {where}."
        else:
            msg = f"Profile '{result.name}' imported."
        messagebox.showinfo("Import Complete", msg)

    def _ask_mods_target(self, versions):
        """Dialog: which installed version gets a plain mods zip. None = cancel."""
        win = tk.Toplevel(self.window)
        win.title("Install mods into...")
        win.configure(bg=self.colors["bg"])
        win.transient(self.window)
        win.grab_set()
        ttk.Label(
            win,
            text="This zip only contains mods. Which version should get them?",
            padding=10,
        ).pack(anchor=tk.W)
        choices = versions + ["Shared mods folder (all versions)"]
        listbox = tk.Listbox(win, height=min(10, len(choices)), width=48)
        for c in choices:
            listbox.insert(tk.END, c)
        listbox.selection_set(0)
        listbox.pack(fill=tk.BOTH, expand=True, padx=10)
        box = {"v": None}

        def ok():
            sel = listbox.curselection()
            if sel:
                box["v"] = "" if sel[0] == len(versions) else versions[sel[0]]
            win.destroy()

        btns = ttk.Frame(win, padding=10)
        btns.pack(fill=tk.X)
        ttk.Button(btns, text="Install", command=ok).pack(side=tk.RIGHT)
        ttk.Button(btns, text="Cancel", command=win.destroy).pack(side=tk.RIGHT, padx=6)
        listbox.bind("<Double-Button-1>", lambda _e: ok())
        self.window.wait_window(win)
        return box["v"]

    def _collect_profile_info(self, selected_idx):
        """Gather all info + mods for the profile at the given listbox index.

        Returns a dict of the parsed fields, or None if the index is invalid.
        Raises on unexpected errors so the caller can surface them.
        """

        profiles_file = APP_DIR / "home" / "launcher_profiles.json"
        with open(profiles_file) as f:
            data = json.load(f)

        profiles = data.get("profiles", {})
        profile_keys = list(profiles.keys())
        if selected_idx >= len(profile_keys):
            return None

        profile_id = profile_keys[selected_idx]
        profile_data = profiles[profile_id]
        profile_name = profile_data.get("name", profile_id)
        version_id = profile_data.get("lastVersionId", "unknown")
        profile_type = profile_data.get("type", "custom")
        game_dir = profile_data.get("gameDir", "")

        version_dir = APP_DIR / "home" / "versions" / version_id

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
            mods_dir = APP_DIR / "home" / rel / "mods"
        else:
            mods_dir = APP_DIR / "home" / "mods"

        active_mods = []
        disabled_mods = []
        if mods_dir.exists():
            for entry in sorted(mods_dir.iterdir()):
                name = entry.name
                if name.endswith(".jar.deactivation"):
                    disabled_mods.append(name[: -len(".deactivation")])
                elif name.endswith(".jar"):
                    active_mods.append(name)

        return {
            "profile_name": profile_name,
            "profile_type": profile_type,
            "mc_version": mc_version,
            "modloader": modloader,
            "modloader_version": modloader_version,
            "java_version": java_version,
            "version_id": version_id,
            "active_mods": active_mods,
            "disabled_mods": disabled_mods,
        }

    def _format_profile_info_text(self, info):
        """Render a profile info dict as a plain-text block for the clipboard."""
        ml_label = f"{info['modloader']} {info['modloader_version']}".strip()
        active = info["active_mods"]
        disabled = info["disabled_mods"]
        total = len(active) + len(disabled)

        lines = [
            f"Profile:    {info['profile_name']}",
            f"Type:       {info['profile_type']}",
            f"MC Version: {info['mc_version']}",
            f"Modloader:  {ml_label}",
            f"Java:       Java {info['java_version']}",
            f"Version ID: {info['version_id']}",
            "",
            f"Mods total: {total}  (active: {len(active)}, disabled: {len(disabled)})",
        ]
        if active or disabled:
            lines.append("")
            lines.append("Mods:")
            for name in active:
                lines.append(f"  [x] {name}")
            for name in disabled:
                lines.append(f"  [ ] {name}")
        return "\n".join(lines)

    def copy_profile_info(self):
        """Copy the selected profile's full info + mod list to the clipboard."""

        selection = self.profiles_listbox.curselection()
        if not selection:
            messagebox.showwarning("No Selection", "Please select a profile to copy its info.")
            return
        try:
            info = self._collect_profile_info(selection[0])
            if info is None:
                messagebox.showerror("Error", "Invalid profile selection.")
                return
            text = self._format_profile_info_text(info)
            self.window.clipboard_clear()
            self.window.clipboard_append(text)
            self.window.update_idletasks()
            self.log(f"(Copied info for '{info['profile_name']}' to clipboard)")
        except Exception as e:
            messagebox.showerror("Error", f"Could not copy profile info:\n{e}")

    def show_profile_info(self):
        """Show detailed info for the selected profile."""

        selection = self.profiles_listbox.curselection()
        if not selection:
            messagebox.showwarning("No Selection", "Please select a profile to view its info.")
            return

        try:
            info = self._collect_profile_info(selection[0])
            if info is None:
                messagebox.showerror("Error", "Invalid profile selection.")
                return

            profile_name = info["profile_name"]
            profile_type = info["profile_type"]
            mc_version = info["mc_version"]
            modloader = info["modloader"]
            modloader_version = info["modloader_version"]
            java_version = info["java_version"]
            version_id = info["version_id"]
            active_mods = info["active_mods"]
            disabled_mods = info["disabled_mods"]

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

            btn_row = ttk.Frame(frame)
            btn_row.pack(fill=tk.X, pady=(12, 0))
            ttk.Button(
                btn_row,
                text="📋 Copy Info",
                command=self.copy_profile_info,
                width=14,
            ).pack(side=tk.LEFT)
            ttk.Button(btn_row, text="Close", command=win.destroy, width=10).pack(side=tk.RIGHT)

            win.update_idletasks()
            # Size to content, but clamp to the screen so the buttons are never
            # pushed off the bottom on QHD/HiDPI. The mod list expands/scrolls to
            # absorb any overflow, keeping the button row visible.
            sw = win.winfo_screenwidth()
            sh = win.winfo_screenheight()
            w = min(max(win.winfo_reqwidth(), 520), sw - 80)
            h = min(win.winfo_reqheight(), sh - 120)
            x = self.window.winfo_x() + (self.window.winfo_width() - w) // 2
            y = self.window.winfo_y() + (self.window.winfo_height() - h) // 2
            x = max(0, min(x, sw - w))
            y = max(0, min(y, sh - h))
            win.geometry(f"{w}x{h}+{x}+{y}")

        except Exception as e:
            messagebox.showerror("Error", f"Could not load profile info:\n{e}")

    def _schedule_service_poll(self):
        """Main-thread tick: apply the last service result and kick a fresh check.

        tkinter is not thread-safe, so the UI is only ever touched here (on the
        main thread, via `after`). The worker thread just stashes a plain tuple in
        self._svc_result and never calls into Tk.
        """
        res = self._svc_result
        if res is not None:
            ok = self.colors["success"]
            off = "#555555"
            self.podman_svc_label.config(foreground=ok if res[0] else off)
            self.docker_svc_label.config(foreground=ok if res[1] else off)
        if not self._svc_worker_busy:
            self._svc_worker_busy = True
            threading.Thread(target=self._svc_worker, daemon=True).start()
        self._svc_poll_job = self.window.after(4000, self._schedule_service_poll)

    def _svc_worker(self):
        """Background: probe runtime availability; stash result (no Tk access).

        A runtime is 'up' if `<rt> ps` responds (returncode 0) - that's what the
        launcher actually needs. This is more meaningful than the old
        podman.socket/docker.service systemd check, which read as 'down' for
        rootless podman even though podman was fully working.
        """

        def _runtime_ok(rt):
            try:
                return subprocess.run([rt, "ps"], capture_output=True, timeout=4).returncode == 0
            except Exception:
                return False

        try:
            self._svc_result = (_runtime_ok("podman"), _runtime_ok("docker"))
        finally:
            self._svc_worker_busy = False

    def _sync_control_buttons(self, running):
        """Set the control buttons to match the real container state.

        Ground truth is whether the container is actually running:
        - running is True: the container is up, so Stop/Restart MUST be usable -
          even mid-transition and even if the "Started!" log line was never seen
          (which is exactly the case that used to leave them disabled for ~20s).
        - running is False, and no start/stop is in flight: reset to the stopped
          layout. While a transition IS in flight we leave the buttons as-is, so
          a just-clicked Start doesn't briefly re-enable itself before the
          container has had time to appear.
        - running is None: no poll result yet; do nothing.
        """
        if running is None:
            return
        # Doctor is always available (read-only diagnostic).
        self.btn_doctor.config(state=tk.NORMAL)
        if running:
            self.btn_start.config(state=tk.DISABLED)
            self.btn_stop.config(state=tk.NORMAL)
            self.btn_restart.config(state=tk.NORMAL)
        elif not self._in_transition():
            self.btn_start.config(state=tk.NORMAL)
            self.btn_stop.config(state=tk.DISABLED)
            self.btn_restart.config(state=tk.DISABLED)

    def _in_transition(self) -> bool:
        """True while a start/stop/restart is in flight, bounded to 20s.

        The bound guarantees the state poller can't be frozen out forever if a
        transition's terminal callback (e.g. the "started" signal) never fires.
        """
        return self._transition_at != 0.0 and (time.monotonic() - self._transition_at) < 20.0

    def _container_is_running(self, config) -> bool:
        """True only if the tlauncher container is actually in the running state.

        Uses `<runtime> ps` (which lists running containers only) filtered by the
        fixed container name, so a stopped/exited container that still shows up in
        `compose ps` output does not read as running (which would wrongly disable
        the Start button).
        """

        runtime = config.get("runtime", "podman")
        try:
            result = subprocess.run(
                [runtime, "ps", "--filter", "name=^tlauncher$", "--format", "{{.Names}}"],
                capture_output=True,
                text=True,
                timeout=5,
            )
            return result.returncode == 0 and "tlauncher" in result.stdout.split()
        except Exception:
            return False

    def _schedule_state_poll(self):
        """Main-thread tick: apply the last known container state, kick a fresh
        check, and reschedule. Only this method (main thread) touches the Tk
        buttons; the worker thread just stashes a bool in self._last_running.
        """
        # _sync_control_buttons applies its own running/transition logic.
        self._sync_control_buttons(self._last_running)
        if not self._state_worker_busy:
            self._state_worker_busy = True
            # Gather config on the main thread (it reads Tk widgets).
            config = self._gather_config()
            threading.Thread(target=self._state_worker, args=(config,), daemon=True).start()
        self._state_poll_job = self.window.after(2000, self._schedule_state_poll)

    def _state_worker(self, config):
        """Background: probe real container state; stash result (no Tk access)."""
        try:
            self._last_running = self._container_is_running(config)
        finally:
            self._state_worker_busy = False

    def _check_for_updates_async(self):
        """Background thread: compare local HEAD SHA with remote and surface a banner if behind."""

        repo = str(APP_DIR)
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

        confirm = messagebox.askyesno(
            "Update Launcher",
            "Pull the latest changes from GitHub?\n\n"
            "The launcher will update but you must restart it manually afterwards.",
        )
        if not confirm:
            return

        self.log("\n⬆ Fetching changes from origin…")
        repo = str(APP_DIR)

        def _pull():
            fetch = subprocess.run(["git", "fetch"], capture_output=True, text=True, cwd=repo)
            if fetch.returncode != 0:

                def _fetch_err():
                    self.log(f"✗ git fetch failed:\n{fetch.stderr.strip()}")
                    messagebox.showerror(
                        "Update Failed", f"git fetch failed:\n\n{fetch.stderr.strip()}"
                    )

                self.window.after(0, _fetch_err)
                return

            log_out = subprocess.run(
                ["git", "log", "HEAD..FETCH_HEAD", "--format=  %h %s"],
                capture_output=True,
                text=True,
                cwd=repo,
            ).stdout.strip()

            def _show_commits():
                if log_out:
                    self.log("\nIncoming commits:")
                    for line in log_out.splitlines():
                        self.log(line)
                else:
                    self.log("  (already up to date)")

            self.window.after(0, _show_commits)

            result = subprocess.run(["git", "pull"], capture_output=True, text=True, cwd=repo)

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
