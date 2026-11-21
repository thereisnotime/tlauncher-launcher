"""Constants shared by the GUI modules."""

from pathlib import Path

from core.version import app_version, version_string

# Repository root: profiles, pyproject.toml, Containerfile and icon.png live here.
APP_DIR = Path(__file__).parent.parent


APP_VERSION = app_version()
# Version plus git commit, e.g. "1.1.0 (0b9280b)"; shown in the title bar.
APP_BUILD = version_string()
