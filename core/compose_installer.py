"""
Install a standalone Docker Compose v2 binary for `podman compose` to use.

Without a v2 provider, podman falls back to the legacy python podman-compose
(buffered output, fewer features). This fetches the official release binary
into ~/.local/bin/docker-compose, checked against the published sha256.
Standard library only.
"""

import hashlib
import os
import platform
import tempfile
import urllib.error
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

RELEASE_URL = "https://github.com/docker/compose/releases/latest/download"

# platform.machine() -> suffix used in the release asset names.
_ARCH_MAP = {
    "x86_64": "x86_64",
    "amd64": "x86_64",
    "aarch64": "aarch64",
    "arm64": "aarch64",
    "armv7l": "armv7",
    "armv7": "armv7",
}

_TIMEOUT = 30
_CHUNK = 1 << 16


@dataclass
class InstallResult:
    ok: bool
    message: str
    path: Path | None = None


def default_target() -> Path:
    """Where the binary goes by default (detector.py also looks here)."""
    return Path.home() / ".local" / "bin" / "docker-compose"


def asset_name(machine: str | None = None) -> str:
    """Return the release asset name for this machine, or raise ValueError."""
    machine = (machine or platform.machine()).lower()
    arch = _ARCH_MAP.get(machine)
    if not arch:
        raise ValueError(f"No Docker Compose release for architecture '{machine}'")
    return f"docker-compose-linux-{arch}"


def _open(url: str):
    req = urllib.request.Request(url, headers={"User-Agent": "tlauncher-launcher"})
    return urllib.request.urlopen(req, timeout=_TIMEOUT)


def _fetch_checksum(url: str) -> str:
    """Read '<sha256>  <name>' from the .sha256 file and return the hex digest."""
    with _open(url) as resp:
        text = resp.read(4096).decode("utf-8", "replace").strip()
    digest = text.split()[0].lower() if text else ""
    if len(digest) != 64 or any(c not in "0123456789abcdef" for c in digest):
        raise ValueError(f"Unexpected checksum file contents from {url}")
    return digest


def install_docker_compose(
    target: Path | None = None,
    log: Callable[[str], None] | None = None,
    base_url: str = RELEASE_URL,
    machine: str | None = None,
) -> InstallResult:
    """
    Download Docker Compose v2 to `target` (default ~/.local/bin/docker-compose).

    The binary is streamed to a temp file next to the target, verified against
    the release's .sha256, chmod 755'd and atomically renamed into place, so a
    failed or interrupted download never leaves a broken binary behind.
    """
    log = log or (lambda _msg: None)
    target = Path(target).expanduser() if target else default_target()

    if platform.system() != "Linux":
        return InstallResult(False, "Automatic install only supports Linux")

    try:
        name = asset_name(machine)
    except ValueError as e:
        return InstallResult(False, str(e))

    url = f"{base_url}/{name}"
    tmp_path = None
    try:
        target.parent.mkdir(parents=True, exist_ok=True)

        log(f"Fetching checksum: {url}.sha256")
        expected = _fetch_checksum(f"{url}.sha256")

        log(f"Downloading {url}")
        sha = hashlib.sha256()
        fd, tmp_name = tempfile.mkstemp(prefix=".docker-compose-", dir=target.parent)
        tmp_path = Path(tmp_name)
        size = 0
        with os.fdopen(fd, "wb") as out, _open(url) as resp:
            while True:
                chunk = resp.read(_CHUNK)
                if not chunk:
                    break
                out.write(chunk)
                sha.update(chunk)
                size += len(chunk)
        log(f"Downloaded {size / 1_048_576:.1f} MiB")

        actual = sha.hexdigest()
        if actual != expected:
            return InstallResult(
                False, f"Checksum mismatch for {name}: expected {expected}, got {actual}"
            )
        log("Checksum OK")

        tmp_path.chmod(0o755)
        tmp_path.replace(target)
        tmp_path = None
    except urllib.error.HTTPError as e:
        return InstallResult(False, f"Download failed: HTTP {e.code} for {e.url}")
    except urllib.error.URLError as e:
        return InstallResult(False, f"Download failed: {e.reason}")
    except (OSError, ValueError) as e:
        return InstallResult(False, f"Install failed: {e}")
    finally:
        if tmp_path is not None:
            try:
                tmp_path.unlink()
            except OSError:
                pass

    msg = f"Installed Docker Compose v2 to {target}"
    on_path = str(target.parent) in os.environ.get("PATH", "").split(os.pathsep)
    if target == default_target() and not on_path:
        msg += f" ({target.parent} isn't on PATH, but the launcher finds it there)"
    return InstallResult(True, msg, target)
