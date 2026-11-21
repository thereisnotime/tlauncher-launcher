"""Constants shared by the GUI modules."""

import re
from pathlib import Path

# Repository root: profiles, pyproject.toml, Containerfile and icon.png live here.
APP_DIR = Path(__file__).parent.parent


def _read_app_version() -> str:
    try:
        toml = (APP_DIR / "pyproject.toml").read_text()
        m = re.search(r'^version\s*=\s*"([^"]+)"', toml, re.MULTILINE)
        return m.group(1) if m else "1.0.0"
    except Exception:
        return "1.0.0"


APP_VERSION = _read_app_version()
