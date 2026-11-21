"""
System validation module for Craftainer.
Performs pre-flight checks to ensure system is ready.
"""

import os
import shutil
import subprocess
from pathlib import Path

from .detector import (
    detect_compose_provider,
    has_legacy_podman_compose,
    podman_socket_path,
    podman_socket_ready,
)

# ValidationIssue.code for "podman has no Docker Compose v2 provider"; the GUI
# uses it to offer core.compose_installer.
COMPOSE_V2_MISSING = "compose_v2_missing"
PODMAN_SOCKET_DOWN = "podman_socket_down"
GAME_RAM_TOO_HIGH = "game_ram_too_high"


class ValidationIssue:
    """Represents a validation issue."""

    def __init__(self, message: str, level: str = "error", fix_hint: str = None, code: str = None):
        """
        Initialize validation issue.

        Args:
            message: Description of the issue
            level: 'error' (blocking) or 'warning' (non-blocking)
            fix_hint: Optional suggestion for fixing the issue
            code: Optional stable identifier so callers can offer a fix
        """
        self.message = message
        self.level = level
        self.fix_hint = fix_hint
        self.code = code

    def is_blocking(self) -> bool:
        """Check if this issue prevents startup."""
        return self.level == "error"


def validate_system(config: dict[str, str]) -> tuple[bool, list[ValidationIssue]]:
    """
    Perform all validation checks.

    Args:
        config: Configuration dict

    Returns:
        tuple: (is_valid, list_of_issues)
    """
    issues = []

    # Run all validation checks
    issues.extend(_check_runtime(config))
    issues.extend(_check_compose_provider(config))
    issues.extend(_check_game_ram(config))
    issues.extend(_check_gpu(config))
    issues.extend(_check_display(config))
    issues.extend(_check_audio(config))
    issues.extend(_check_compose_files(config))
    issues.extend(_check_xhost(config))

    # System is valid only if there are no blocking errors
    has_errors = any(issue.is_blocking() for issue in issues)

    return not has_errors, issues


def _check_runtime(config: dict[str, str]) -> list[ValidationIssue]:
    """Check if container runtime is available."""
    issues = []
    runtime = config["runtime"]

    if not shutil.which(runtime):
        issues.append(
            ValidationIssue(
                f"{runtime} is not installed or not in PATH",
                level="error",
                fix_hint=f"Install {runtime}: https://{runtime}.io/getting-started/installation",
            )
        )
    else:
        # Try to run runtime --version to ensure it works
        try:
            result = subprocess.run([runtime, "--version"], capture_output=True, timeout=5)
            if result.returncode != 0:
                issues.append(
                    ValidationIssue(
                        f"{runtime} is installed but not working properly",
                        level="error",
                        fix_hint=f"Try running '{runtime} --version' manually to see the error",
                    )
                )
        except subprocess.TimeoutExpired:
            issues.append(ValidationIssue(f"{runtime} command timed out", level="warning"))
        except Exception as e:
            issues.append(ValidationIssue(f"Error checking {runtime}: {str(e)}", level="warning"))

    return issues


def _check_game_ram(config: dict[str, str]) -> list[ValidationIssue]:
    """Warn if Minecraft's heap won't fit inside the container's memory cap."""
    from .game_ram import get_game_ram, max_game_ram, mem_limit_mb

    current = get_game_ram()
    cap = mem_limit_mb(config.get("memory", "8g"))
    if current is None or current <= max_game_ram(cap):
        return []
    return [
        ValidationIssue(
            f"Minecraft is set to use {current} MB, but the container is capped at "
            f"{cap} MB; it will be killed when the heap fills up",
            level="warning",
            fix_hint=f"Lower it to {max_game_ram(cap)} MB or less "
            f"(./minecraft.py game-ram {max_game_ram(cap)}), or raise the Memory setting",
            code=GAME_RAM_TOO_HIGH,
        )
    ]


def _check_compose_provider(config: dict[str, str]) -> list[ValidationIssue]:
    """Make sure `podman compose` has a provider that will actually work."""
    if config["runtime"] != "podman" or os.environ.get("PODMAN_COMPOSE_PROVIDER"):
        return []
    if has_legacy_podman_compose():
        return []  # podman-compose: podman-native, preferred
    if detect_compose_provider("podman"):
        if podman_socket_ready():
            return []
        # docker-compose talks to podman's API socket, which isn't running.
        return [
            ValidationIssue(
                f"Docker Compose is installed but podman's API socket "
                f"({podman_socket_path()}) isn't running",
                level="error",
                fix_hint="Install podman-compose (e.g. 'sudo dnf install podman-compose' / "
                "'sudo apt install podman-compose'), or start the socket: "
                "'systemctl --user enable --now podman.socket'",
                code=PODMAN_SOCKET_DOWN,
            )
        ]
    return [
        ValidationIssue(
            "No compose provider found; 'podman compose' has nothing to run",
            level="error",
            fix_hint="Install podman-compose (e.g. 'sudo dnf install podman-compose' / "
            "'sudo apt install podman-compose'), or run './minecraft.py install-compose' "
            "and 'systemctl --user enable --now podman.socket'",
            code=COMPOSE_V2_MISSING,
        )
    ]


def _check_gpu(config: dict[str, str]) -> list[ValidationIssue]:
    """Check if GPU devices exist."""
    issues: list[ValidationIssue] = []
    gpu = config["gpu"]

    # Under WSLg the GPU comes via /dev/dxg + the WSL driver libs, not the usual
    # host devices, so the standard checks don't apply.
    if config.get("display") == "wslg":
        return issues

    if gpu == "nvidia":
        if not Path("/dev/nvidia0").exists():
            issues.append(
                ValidationIssue(
                    "NVIDIA GPU selected but /dev/nvidia0 not found",
                    level="error",
                    fix_hint="Install NVIDIA drivers or select 'amd' GPU type",
                )
            )
        if not Path("/dev/nvidiactl").exists():
            issues.append(
                ValidationIssue(
                    "/dev/nvidiactl device not found",
                    level="warning",
                    fix_hint="NVIDIA drivers may not be properly installed",
                )
            )
    elif gpu in ("amd", "intel"):
        if not Path("/dev/dri").exists():
            issues.append(
                ValidationIssue(
                    "/dev/dri not found - no GPU acceleration available",
                    level="warning",
                    fix_hint="Install Mesa drivers for GPU acceleration",
                )
            )

    return issues


def _check_display(config: dict[str, str]) -> list[ValidationIssue]:
    """Check if display server is available."""
    issues = []
    display = config["display"]

    if display == "x11":
        if not os.environ.get("DISPLAY"):
            issues.append(
                ValidationIssue(
                    "X11 selected but DISPLAY environment variable not set",
                    level="error",
                    fix_hint="Ensure you're running in an X11 session",
                )
            )
        if not Path("/tmp/.X11-unix").exists():
            issues.append(
                ValidationIssue("X11 socket directory /tmp/.X11-unix not found", level="warning")
            )
    elif display == "wayland":
        if not os.environ.get("WAYLAND_DISPLAY"):
            issues.append(
                ValidationIssue(
                    "Wayland selected but WAYLAND_DISPLAY not set",
                    level="warning",
                    fix_hint="Ensure you're running in a Wayland session",
                )
            )
        # Java/Swing (TLauncher) runs via XWayland, which needs DISPLAY + the X socket.
        if not os.environ.get("DISPLAY"):
            issues.append(
                ValidationIssue(
                    "DISPLAY not set; TLauncher (Java) needs XWayland to show a window",
                    level="error",
                    fix_hint="Ensure XWayland is running (default on GNOME/KDE Wayland sessions)",
                )
            )
        if not Path("/tmp/.X11-unix").exists():
            issues.append(
                ValidationIssue(
                    "X11 socket /tmp/.X11-unix not found (needed for XWayland)",
                    level="warning",
                )
            )
    elif display == "wslg":
        if not Path("/mnt/wslg").exists():
            issues.append(
                ValidationIssue(
                    "WSLg not found at /mnt/wslg",
                    level="error",
                    fix_hint="Update WSL ('wsl --update') and use WSL2 with WSLg (Windows 11)",
                )
            )
        if not os.environ.get("DISPLAY"):
            issues.append(
                ValidationIssue(
                    "DISPLAY not set; WSLg should provide it",
                    level="warning",
                    fix_hint="Restart WSL ('wsl --shutdown') so WSLg initializes",
                )
            )

    return issues


def _check_audio(config: dict[str, str]) -> list[ValidationIssue]:
    """Check if audio system is available."""
    issues: list[ValidationIssue] = []
    audio = config["audio"]

    # WSLg provides its own audio path (/mnt/wslg/PulseServer); skip host checks.
    if config.get("display") == "wslg":
        return issues

    if audio == "pulseaudio":
        uid = os.getuid()
        pulse_socket = Path(f"/run/user/{uid}/pulse/native")

        if not pulse_socket.exists():
            issues.append(
                ValidationIssue(
                    f"PulseAudio socket not found at {pulse_socket}",
                    level="warning",
                    fix_hint="Audio may not work. Start PulseAudio/PipeWire or select 'none' for audio",
                )
            )

        if not Path("/dev/snd").exists():
            issues.append(
                ValidationIssue(
                    "/dev/snd not found - ALSA devices unavailable",
                    level="warning",
                    fix_hint="Audio hardware may not be accessible",
                )
            )

    return issues


def _check_compose_files(config: dict[str, str]) -> list[ValidationIssue]:
    """Check if all compose files exist."""
    from .composer import get_compose_directory, validate_compose_files_exist

    issues = []
    all_exist, missing = validate_compose_files_exist(config)

    if not all_exist:
        compose_dir = get_compose_directory()
        for f in missing:
            issues.append(
                ValidationIssue(
                    f"Compose file not found: {compose_dir / f}",
                    level="error",
                    fix_hint=f"Ensure {f} exists in {compose_dir}",
                )
            )

    return issues


def _check_xhost(config: dict[str, str]) -> list[ValidationIssue]:
    """Check if xhost permissions are set for X11."""
    issues = []

    if config["display"] in ("x11", "wayland", "wslg") and config.get("auto_xhost", True):
        # Check if xhost command is available
        if not shutil.which("xhost"):
            issues.append(
                ValidationIssue(
                    "xhost command not found",
                    level="warning",
                    fix_hint="Install xhost or manually allow X11 access",
                )
            )
        else:
            # Try to run xhost to check current access control
            try:
                result = subprocess.run(["xhost"], capture_output=True, text=True, timeout=2)
                if result.returncode == 0:
                    # Check if localuser access is already granted
                    if "SI:localuser:" not in result.stdout:
                        issues.append(
                            ValidationIssue(
                                "X11 access may need to be granted",
                                level="warning",
                                fix_hint="Will attempt to run: xhost +SI:localuser:$USER",
                            )
                        )
            except Exception:
                pass

    return issues


def run_xhost_if_needed(config: dict[str, str]) -> bool:
    """
    Run xhost command to allow X11 access if needed.

    Args:
        config: Configuration dict

    Returns:
        bool: True if successful or not needed
    """
    # XWayland (Wayland) and WSLg are X servers too, so they need the grant as well.
    if config["display"] not in ("x11", "wayland", "wslg") or not config.get("auto_xhost", True):
        return True

    if not shutil.which("xhost"):
        return False

    try:
        username = os.getenv("USER", os.getenv("USERNAME", ""))
        if not username:
            return False

        result = subprocess.run(
            ["xhost", f"+SI:localuser:{username}"], capture_output=True, timeout=5
        )
        return result.returncode == 0
    except Exception:
        return False
