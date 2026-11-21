# mypy: disable-error-code="attr-defined, has-type"
# (mixin: self is MinecraftLauncherGUI at runtime, which mypy cannot see here)
"""Container control: start, stop, restart, image rebuild, Compose v2 install offer."""

import subprocess
import threading
import time
import tkinter as tk
from tkinter import messagebox

from core.compose_installer import default_target, install_docker_compose
from core.composer import get_command_preview
from core.container import (
    ContainerManager,
    build_image_command,
    image_exists,
    image_tag,
    start_container_async,
)
from core.detector import detect_compose_provider
from core.log_analyzer import analyze_lines
from core.validator import COMPOSE_V2_MISSING, run_xhost_if_needed, validate_system
from ui.common import APP_DIR


class ContainerControlMixin:
    """Start/Stop/Restart/Rebuild handlers and the Docker Compose v2 installer prompt."""

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
