"""
GUI interface for Minecraft Launcher.
Provides graphical Tkinter-based interaction.
"""
import tkinter as tk
from tkinter import ttk, scrolledtext, messagebox
import threading
from pathlib import Path
from typing import Dict

from core.detector import detect_system, get_detection_details
from core.config import load_config, save_config, merge_config
from core.validator import validate_system, run_xhost_if_needed
from core.container import start_container_async, ContainerManager
from core.composer import get_command_preview


class MinecraftLauncherGUI:
    """Main GUI application for Minecraft Launcher."""

    def __init__(self):
        """Initialize the GUI."""
        self.window = tk.Tk()
        self.window.title("Minecraft Launcher Launcher")
        self.window.geometry("800x700")
        self.window.minsize(750, 650)
        self.window.resizable(True, True)

        # X11: window icon and class so taskbar/dock shows our icon
        self._set_window_icon()
        # WM_CLASS for taskbar/dock (wm_class not available on all Tk builds)
        try:
            self.window.tk.call("wm", "class", self.window._w, "minecraft-launcher", "MinecraftLauncher")
        except (AttributeError, tk.TclError):
            pass

        self.config = {}
        self.detected = {}
        self.manager = None
        self._user_requested_stop = False

        self._create_widgets()
        self._detect_and_load()

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
        # Main container
        main_frame = ttk.Frame(self.window, padding="10")
        main_frame.grid(row=0, column=0, sticky=(tk.W, tk.E, tk.N, tk.S))
        self.window.columnconfigure(0, weight=1)
        self.window.rowconfigure(0, weight=1)

        # Detection Frame
        detect_frame = ttk.LabelFrame(main_frame, text="Configuration", padding="10")
        detect_frame.grid(row=0, column=0, columnspan=2, sticky=(tk.W, tk.E), pady=(0, 10))

        # Runtime
        ttk.Label(detect_frame, text="Runtime:").grid(row=0, column=0, sticky=tk.W, padx=(0, 10))
        self.runtime_var = tk.StringVar()
        self.runtime_combo = ttk.Combobox(detect_frame, textvariable=self.runtime_var,
                                          values=['auto', 'podman', 'docker'], state='readonly', width=15)
        self.runtime_combo.grid(row=0, column=1, sticky=tk.W)
        self.runtime_status_label = ttk.Label(detect_frame, text="", foreground="gray")
        self.runtime_status_label.grid(row=0, column=2, sticky=tk.W, padx=(10, 0))

        # GPU
        ttk.Label(detect_frame, text="GPU:").grid(row=1, column=0, sticky=tk.W, padx=(0, 10), pady=(5, 0))
        self.gpu_var = tk.StringVar()
        self.gpu_combo = ttk.Combobox(detect_frame, textvariable=self.gpu_var,
                                      values=['auto', 'nvidia', 'amd'], state='readonly', width=15)
        self.gpu_combo.grid(row=1, column=1, sticky=tk.W, pady=(5, 0))
        self.gpu_status_label = ttk.Label(detect_frame, text="", foreground="gray")
        self.gpu_status_label.grid(row=1, column=2, sticky=tk.W, padx=(10, 0), pady=(5, 0))

        # Display
        ttk.Label(detect_frame, text="Display:").grid(row=2, column=0, sticky=tk.W, padx=(0, 10), pady=(5, 0))
        self.display_var = tk.StringVar()
        self.display_combo = ttk.Combobox(detect_frame, textvariable=self.display_var,
                                          values=['auto', 'x11', 'wayland'], state='readonly', width=15)
        self.display_combo.grid(row=2, column=1, sticky=tk.W, pady=(5, 0))
        self.display_status_label = ttk.Label(detect_frame, text="", foreground="gray")
        self.display_status_label.grid(row=2, column=2, sticky=tk.W, padx=(10, 0), pady=(5, 0))

        # Audio
        ttk.Label(detect_frame, text="Audio:").grid(row=3, column=0, sticky=tk.W, padx=(0, 10), pady=(5, 0))
        self.audio_var = tk.StringVar()
        self.audio_combo = ttk.Combobox(detect_frame, textvariable=self.audio_var,
                                        values=['auto', 'pulseaudio', 'none'], state='readonly', width=15)
        self.audio_combo.grid(row=3, column=1, sticky=tk.W, pady=(5, 0))
        self.audio_status_label = ttk.Label(detect_frame, text="", foreground="gray")
        self.audio_status_label.grid(row=3, column=2, sticky=tk.W, padx=(10, 0), pady=(5, 0))

        detect_frame.columnconfigure(2, weight=1)

        # Control Buttons Frame
        control_frame = ttk.Frame(main_frame)
        control_frame.grid(row=1, column=0, columnspan=2, sticky=(tk.W, tk.E), pady=(0, 10))

        self.btn_start = ttk.Button(control_frame, text="Start", command=self.start_minecraft, width=12)
        self.btn_start.pack(side=tk.LEFT, padx=(0, 5))

        self.btn_stop = ttk.Button(control_frame, text="Stop", command=self.stop_minecraft,
                                    state=tk.DISABLED, width=12)
        self.btn_stop.pack(side=tk.LEFT, padx=5)

        self.btn_restart = ttk.Button(control_frame, text="Restart", command=self.restart_minecraft,
                                      state=tk.DISABLED, width=12)
        self.btn_restart.pack(side=tk.LEFT, padx=5)

        self.btn_doctor = ttk.Button(control_frame, text="Doctor", command=self.run_doctor, width=12)
        self.btn_doctor.pack(side=tk.LEFT, padx=5)

        self.btn_save = ttk.Button(control_frame, text="Save Config", command=self.save_configuration, width=12)
        self.btn_save.pack(side=tk.LEFT, padx=5)

        self.btn_edit = ttk.Button(control_frame, text="Edit Config", command=self.edit_configuration, width=12)
        self.btn_edit.pack(side=tk.LEFT, padx=5)

        # Make main_frame columns expand properly
        main_frame.columnconfigure(0, weight=1)
        main_frame.columnconfigure(1, weight=1)

        # Status Label
        self.status_label = ttk.Label(main_frame, text="Status: Ready", font=('', 10, 'bold'))
        self.status_label.grid(row=2, column=0, columnspan=2, sticky=tk.W, pady=(0, 5))

        # Log Output Frame
        log_frame = ttk.LabelFrame(main_frame, text="Output", padding="10")
        log_frame.grid(row=3, column=0, columnspan=2, sticky=(tk.W, tk.E, tk.N, tk.S))
        log_frame.columnconfigure(0, weight=1)
        log_frame.rowconfigure(0, weight=1)
        main_frame.rowconfigure(3, weight=1)

        self.log_text = scrolledtext.ScrolledText(log_frame, height=20, wrap=tk.WORD)
        self.log_text.grid(row=0, column=0, sticky=(tk.W, tk.E, tk.N, tk.S))

        # Log buttons in a frame so they stay visible and aren't cut off
        log_btn_frame = ttk.Frame(log_frame)
        log_btn_frame.grid(row=1, column=0, sticky=(tk.W, tk.E), pady=(8, 2))
        btn_clear = ttk.Button(log_btn_frame, text="Clear Logs", command=self.clear_logs)
        btn_clear.pack(side=tk.LEFT, padx=(0, 5))
        btn_copy = ttk.Button(log_btn_frame, text="Copy all logs", command=self.copy_logs)
        btn_copy.pack(side=tk.LEFT)

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
        self.log("\nReady to start!")

    def _update_ui_from_config(self):
        """Update UI dropdowns from current config."""
        self.runtime_var.set('auto' if not self.config.get('runtime') or self.config['runtime'] == self.detected['runtime'] else self.config['runtime'])
        self.gpu_var.set('auto' if not self.config.get('gpu') or self.config['gpu'] == self.detected['gpu'] else self.config['gpu'])
        self.display_var.set('auto' if not self.config.get('display') or self.config['display'] == self.detected['display'] else self.config['display'])
        self.audio_var.set('auto' if not self.config.get('audio') or self.config['audio'] == self.detected['audio'] else self.config['audio'])

        # Update status labels
        self.runtime_status_label.config(text=f"(detected: {self.detected['runtime']})")
        self.gpu_status_label.config(text=f"(detected: {self.detected['gpu']})")
        self.display_status_label.config(text=f"(detected: {self.detected['display']})")
        self.audio_status_label.config(text=f"(detected: {self.detected['audio']})")

    def _gather_config(self) -> Dict[str, str]:
        """Gather configuration from UI."""
        runtime = self.runtime_var.get()
        gpu = self.gpu_var.get()
        display = self.display_var.get()
        audio = self.audio_var.get()

        # Convert 'auto' back to detected values
        return {
            'runtime': self.detected['runtime'] if runtime == 'auto' else runtime,
            'gpu': self.detected['gpu'] if gpu == 'auto' else gpu,
            'display': self.detected['display'] if display == 'auto' else display,
            'audio': self.detected['audio'] if audio == 'auto' else audio,
            'auto_xhost': True
        }

    def start_minecraft(self):
        """Start button handler."""
        config = self._gather_config()

        # Validate
        self.log("\n" + "="*50)
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
            self._update_status("Status: Validation failed", "red")
            messagebox.showerror("Validation Failed",
                                "System validation failed. Check the output for details.")
            return

        self.log("✓ Validation passed")

        # Run xhost if needed
        if config['display'] == 'x11' and config.get('auto_xhost', True):
            self.log("Setting X11 permissions...")
            if run_xhost_if_needed(config):
                self.log("✓ X11 permissions set")
            else:
                self.log("⚠ Could not set X11 permissions automatically")

        # Show command
        self.log(f"\nCommand: {get_command_preview(config, 'up')}\n")

        # Update UI state
        self._update_status("Status: Starting...", "orange")
        self.btn_start.config(state=tk.DISABLED)
        self.btn_doctor.config(state=tk.DISABLED)

        # Start container in background thread
        def output_callback(line):
            self.log(line)

        def started_callback():
            # Launcher GUI is up; run UI update on main thread
            def _on_started():
                self._update_status("Status: Running", "green")
                self.btn_stop.config(state=tk.NORMAL)
                self.btn_restart.config(state=tk.NORMAL)
                self.log("\n✓ Container started successfully")

            self.window.after(0, _on_started)

        def completion_callback(success):
            # Container process exited; run UI update on main thread
            def _on_exited():
                self._update_status("Status: Stopped", "gray")
                self.btn_start.config(state=tk.NORMAL)
                self.btn_stop.config(state=tk.DISABLED)
                self.btn_restart.config(state=tk.DISABLED)
                self.btn_doctor.config(state=tk.NORMAL)
                if self._user_requested_stop:
                    self._user_requested_stop = False
                    # Don't log "exited with error" — we intentionally stopped it
                elif success:
                    self.log("\n✓ Container stopped")
                else:
                    self.log("\n✗ Container exited with error")

            self.window.after(0, _on_exited)

        start_container_async(config, detached=False,
                              output_callback=output_callback,
                              started_callback=started_callback,
                              completion_callback=completion_callback)

    def stop_minecraft(self):
        """Stop button handler."""
        config = self._gather_config()

        self._user_requested_stop = True
        self.log("\n" + "="*50)
        self.log("Stopping container...")
        self._update_status("Status: Stopping...", "orange")

        def stop_worker():
            manager = ContainerManager(config)
            success = manager.stop()

            def _on_stop_done():
                if success:
                    self._update_status("Status: Stopped", "gray")
                    self.btn_start.config(state=tk.NORMAL)
                    self.btn_stop.config(state=tk.DISABLED)
                    self.btn_restart.config(state=tk.DISABLED)
                    self.btn_doctor.config(state=tk.NORMAL)
                    self.log("✓ Container stopped")
                else:
                    self._update_status("Status: Running", "green")
                    self.log("✗ Failed to stop container")

            self.window.after(0, _on_stop_done)

        threading.Thread(target=stop_worker, daemon=True).start()

    def restart_minecraft(self):
        """Restart button handler."""
        config = self._gather_config()

        self.log("\n" + "="*50)
        self.log("Restarting container...")
        self._update_status("Status: Restarting...", "orange")

        def restart_worker():
            manager = ContainerManager(config)

            def output_callback(line):
                self.log(line)

            success = manager.restart(output_callback=output_callback)

            if success:
                self._update_status("Status: Running", "green")
                self.log("\n✓ Container restarted")
            else:
                self._update_status("Status: Failed", "red")
                self.log("\n✗ Failed to restart container")

        threading.Thread(target=restart_worker, daemon=True).start()

    def run_doctor(self):
        """Doctor button handler - run validation."""
        self.log("\n" + "="*50)
        self.log("Running system diagnostics...\n")

        details = get_detection_details()

        # Show detection details
        rt = details['runtime']
        self.log(f"Runtime: {rt['value']} ({rt['path']})")

        gpu = details['gpu']
        self.log(f"GPU: {gpu['details']}")

        disp = details['display']
        self.log(f"Display: {disp['value']} (session: {disp['session_type']})")

        aud = details['audio']
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
            messagebox.showwarning("System Check", "System has validation errors. Check the output for details.")

    def save_configuration(self):
        """Save current configuration."""
        config = self._gather_config()

        # Save with 'auto' converted to empty strings
        save_data = {
            'runtime': '' if self.runtime_var.get() == 'auto' else config['runtime'],
            'gpu': '' if self.gpu_var.get() == 'auto' else config['gpu'],
            'display': '' if self.display_var.get() == 'auto' else config['display'],
            'audio': '' if self.audio_var.get() == 'auto' else config['audio'],
            'auto_xhost': True
        }

        if save_config(save_data):
            self.log("\n✓ Configuration saved")
            messagebox.showinfo("Configuration Saved", "Your configuration has been saved.")
        else:
            self.log("\n✗ Failed to save configuration")
            messagebox.showerror("Save Failed", "Could not save configuration.")

    def edit_configuration(self):
        """Open configuration file in text editor."""
        import subprocess
        import os
        from pathlib import Path

        # Get config file path
        config_dir = Path.home() / '.config' / 'minecraft-launcher'
        config_file = config_dir / 'config.yaml'

        # Create config directory if it doesn't exist
        config_dir.mkdir(parents=True, exist_ok=True)

        # Create empty config file if it doesn't exist
        if not config_file.exists():
            config_file.write_text("# Minecraft Launcher Launcher Configuration\n# Leave values empty to use auto-detection\n\nruntime: ''\ngpu: ''\ndisplay: ''\naudio: ''\nauto_xhost: true\n")
            self.log("\n✓ Created new config file")

        # Open in default text editor
        try:
            if os.name == 'posix':  # Linux/Unix
                subprocess.Popen(['xdg-open', str(config_file)])
            elif os.name == 'nt':  # Windows
                os.startfile(str(config_file))
            else:
                messagebox.showinfo("Config Location", f"Config file location:\n{config_file}")
                return

            self.log(f"\n✓ Opening config file: {config_file}")
            messagebox.showinfo("Config Editor", f"Opening config file in your default editor:\n{config_file}\n\nEdit and save the file, then restart the launcher to apply changes.")
        except Exception as e:
            self.log(f"\n✗ Failed to open config file: {e}")
            messagebox.showerror("Failed to Open", f"Could not open config file.\nLocation: {config_file}\n\nError: {e}")

    def clear_logs(self):
        """Clear the log output."""
        self.log_text.delete('1.0', tk.END)

    def copy_logs(self):
        """Copy full log content to the clipboard."""
        content = self.log_text.get('1.0', tk.END)
        if content.strip():
            self.window.clipboard_clear()
            self.window.clipboard_append(content)
            self.window.update_idletasks()
            self.log("(Logs copied to clipboard)")

    def log(self, message: str):
        """Append message to log output."""
        self.log_text.insert(tk.END, message + '\n')
        self.log_text.see(tk.END)
        self.log_text.update()

    def _update_status(self, text: str, color: str = "black"):
        """Update status label."""
        self.status_label.config(text=text, foreground=color)

    def run(self):
        """Start the GUI main loop."""
        self.window.mainloop()
