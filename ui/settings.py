"""Configuration: detection, dropdown sync, save and edit."""

import os
import subprocess
import sys
import tkinter as tk
from pathlib import Path
from tkinter import messagebox, ttk
from typing import Any

from core.config import (
    default_config_text,
    load_config,
    merge_config,
    normalize_java,
    normalize_memory,
    save_config,
)
from core.detector import detect_system
from core.tray import INSTALL_HINT, pystray_available
from ui.base import GUIBase


class SettingsMixin(GUIBase):
    """Bridges the Configuration dropdowns and core.config/core.detector."""

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

    def _gather_config(self) -> dict[str, Any]:
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
            config_file.write_text(default_config_text())
            self.log("\n✓ Created new config file")

        # Open in default text editor
        try:
            if os.name == "posix":  # Linux/Unix
                subprocess.Popen(["xdg-open", str(config_file)])
            elif sys.platform == "win32":  # Windows (os.name == "nt")
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

    def open_settings_dialog(self):
        """Modal Settings window for launcher preferences that don't need to be on screen."""
        existing: tk.Toplevel | None = getattr(self, "_settings_win", None)
        if existing is not None and existing.winfo_exists():
            existing.lift()
            existing.focus_force()
            return

        win = tk.Toplevel(self.window)
        self._settings_win = win
        win.title("Settings")
        win.transient(self.window)
        win.resizable(False, False)
        win.configure(bg=self.colors["bg"])

        frame = ttk.Frame(win, padding=20)
        frame.pack(fill=tk.BOTH, expand=True)

        # --- Window ---
        ttk.Label(frame, text="Window", font=("Segoe UI", 11, "bold")).pack(anchor=tk.W)
        ttk.Checkbutton(
            frame,
            text="Show a tray icon",
            variable=self.tray_var,
            command=self._on_tray_toggled,
        ).pack(anchor=tk.W, pady=(8, 0))
        ttk.Label(
            frame,
            text="While it's on, closing the window hides the launcher to the tray.\n"
            "Quit from the tray menu. A running game is never stopped by this.",
            foreground="gray",
            font=("Segoe UI", 9),
            justify=tk.LEFT,
        ).pack(anchor=tk.W, padx=(24, 0), pady=(2, 0))
        ok, _why = pystray_available()
        if not ok:
            ttk.Label(
                frame,
                text=INSTALL_HINT,
                foreground=self.colors["warning"],
                font=("Segoe UI", 9),
                wraplength=420,
                justify=tk.LEFT,
            ).pack(anchor=tk.W, padx=(24, 0), pady=(6, 0))

        # --- Config file ---
        ttk.Separator(frame).pack(fill=tk.X, pady=14)
        ttk.Label(frame, text="Config file", font=("Segoe UI", 11, "bold")).pack(anchor=tk.W)
        ttk.Label(
            frame,
            text="Settings take effect immediately. The dropdowns in the main window\n"
            "are kept with 💾 Save Config; everything is also in the config file.",
            foreground="gray",
            font=("Segoe UI", 9),
            justify=tk.LEFT,
        ).pack(anchor=tk.W, pady=(4, 6))
        ttk.Button(frame, text="✏  Open config file", command=self.edit_configuration).pack(
            anchor=tk.W
        )

        btns = ttk.Frame(frame)
        btns.pack(fill=tk.X, pady=(18, 0))
        ttk.Button(btns, text="Close", command=win.destroy, width=10).pack(side=tk.RIGHT)
        win.bind("<Escape>", lambda _e: win.destroy())

        # Center over the main window, then make it modal.
        win.update_idletasks()
        x = self.window.winfo_rootx() + (self.window.winfo_width() - win.winfo_width()) // 2
        y = self.window.winfo_rooty() + (self.window.winfo_height() - win.winfo_height()) // 3
        win.geometry(f"+{max(0, x)}+{max(0, y)}")
        try:
            win.grab_set()
        except tk.TclError:
            pass  # window not viewable yet on some WMs; still usable, just not modal
        win.focus_force()
