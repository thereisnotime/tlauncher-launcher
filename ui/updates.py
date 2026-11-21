# mypy: disable-error-code="attr-defined, has-type"
# (mixin: self is MinecraftLauncherGUI at runtime, which mypy cannot see here)
"""Self-update: compare HEAD with origin and pull on request."""

import subprocess
import threading
import tkinter as tk
from tkinter import messagebox

from ui.common import APP_DIR


class UpdatesMixin:
    """Update-available banner and the git fetch/pull behind its button."""

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
