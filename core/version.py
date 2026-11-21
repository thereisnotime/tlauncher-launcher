"""
Launcher version: the release number from pyproject.toml plus the git commit
the checkout is on, so "what am I running?" has an exact answer.
"""

import re
import subprocess
from functools import lru_cache
from pathlib import Path

REPO_DIR = Path(__file__).resolve().parent.parent


def app_version() -> str:
    """Release number from pyproject.toml (e.g. '1.1.0')."""
    try:
        toml = (REPO_DIR / "pyproject.toml").read_text()
        m = re.search(r'^version\s*=\s*"([^"]+)"', toml, re.MULTILINE)
        return m.group(1) if m else "unknown"
    except OSError:
        return "unknown"


def git_commit() -> str:
    """Short commit of the checkout, '-dirty' if it has local changes; '' if not a git repo."""
    try:
        result = subprocess.run(
            ["git", "-C", str(REPO_DIR), "describe", "--always", "--dirty", "--abbrev=7"],
            capture_output=True,
            text=True,
            timeout=3,
        )
    except (OSError, subprocess.SubprocessError):
        return ""
    return result.stdout.strip() if result.returncode == 0 else ""


@lru_cache(maxsize=1)
def version_string() -> str:
    """'1.1.0 (0b9280b)', or just '1.1.0' outside a git checkout."""
    commit = git_commit()
    return f"{app_version()} ({commit})" if commit else app_version()
