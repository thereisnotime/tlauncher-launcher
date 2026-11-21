# mypy: disable-error-code="attr-defined, has-type"
# (mixin: self is MinecraftLauncherGUI at runtime, which mypy cannot see here)
"""Diagnostics: the Doctor button and the pre-filled GitHub bug report."""

import platform
import subprocess
import urllib.parse
import webbrowser
from tkinter import messagebox

from core.detector import get_detection_details
from core.validator import validate_system
from ui.common import APP_VERSION


class DoctorMixin:
    """Doctor (detection + validation report) and Report Bug."""

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
