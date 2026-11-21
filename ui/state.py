"""Container/runtime state polling that keeps the control buttons in sync."""

import subprocess
import threading
import time
import tkinter as tk


class ContainerStateMixin:
    """Background polls of runtime availability and container state; only the main-thread ticks touch Tk."""

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
            else:
                # Container not running
                self.log("\n🚀 Ready to start!")
                self._update_status("Ready", "success")

        except Exception:
            # If check fails, assume not running
            self.log("\n🚀 Ready to start!")
            self._update_status("Ready", "success")
