"""
Configuration management module for Minecraft Launcher.
Handles loading, saving, and merging user preferences.
"""

from pathlib import Path
from typing import Dict

import yaml

# Configuration file location
CONFIG_DIR = Path.home() / ".config" / "minecraft-launcher"
CONFIG_FILE = CONFIG_DIR / "config.yaml"

# Java inside the container image. It runs the TLauncher app itself; the game
# uses per-version runtimes TLauncher downloads into home/runtime/, so this
# doesn't need to match your Minecraft version. Each choice gets its own image
# tag (tlauncher-java:<ver>) and only the selected one is ever built.
JAVA_VERSIONS = ("21", "25")
DEFAULT_JAVA = "21"


def normalize_java(value) -> str:
    """Return a supported Java version string, falling back to the default."""
    value = str(value or "").strip()
    return value if value in JAVA_VERSIONS else DEFAULT_JAVA


# Container memory cap (compose mem_limit). This is the ceiling for the whole
# container; the game's own heap (-Xmx) is still set in TLauncher's settings
# and has to stay below it.
MEMORY_LIMITS = ("4g", "6g", "8g", "12g", "16g")
DEFAULT_MEMORY = "8g"


def normalize_memory(value) -> str:
    """Return a supported memory limit (e.g. '8g'), falling back to the default."""
    value = str(value or "").strip().lower()
    if value.isdigit():
        value += "g"
    return value if value in MEMORY_LIMITS else DEFAULT_MEMORY


def load_config() -> Dict[str, str]:
    """
    Load saved configuration from file.

    Returns:
        dict: Saved configuration, or empty dict if file doesn't exist
    """
    if not CONFIG_FILE.exists():
        return {}

    try:
        with open(CONFIG_FILE) as f:
            config = yaml.safe_load(f) or {}
            # Ensure all expected keys exist with empty string defaults
            return {
                "runtime": config.get("runtime", ""),
                "gpu": config.get("gpu", ""),
                "display": config.get("display", ""),
                "audio": config.get("audio", ""),
                "java": config.get("java", ""),
                "memory": config.get("memory", ""),
                "auto_xhost": config.get("auto_xhost", True),
            }
    except Exception as e:
        print(f"Warning: Could not load config file: {e}")
        return {}


def save_config(config: Dict[str, any]) -> bool:
    """
    Save configuration to file.

    Args:
        config: Configuration dictionary to save

    Returns:
        bool: True if successful, False otherwise
    """
    try:
        # Create config directory if it doesn't exist
        CONFIG_DIR.mkdir(parents=True, exist_ok=True)

        # Filter out None values and convert to save format
        save_data = {
            "runtime": config.get("runtime", ""),
            "gpu": config.get("gpu", ""),
            "display": config.get("display", ""),
            "audio": config.get("audio", ""),
            "java": config.get("java", ""),
            "memory": config.get("memory", ""),
            "auto_xhost": config.get("auto_xhost", True),
        }

        with open(CONFIG_FILE, "w") as f:
            yaml.dump(save_data, f, default_flow_style=False)

        return True
    except Exception as e:
        print(f"Error: Could not save config file: {e}")
        return False


def merge_config(detected: Dict[str, str], saved: Dict[str, str]) -> Dict[str, str]:
    """
    Merge detected and saved configurations.
    Saved config overrides detection for non-empty values.

    Args:
        detected: Auto-detected configuration
        saved: User-saved configuration

    Returns:
        dict: Merged configuration
    """
    merged = detected.copy()

    # Override with saved config if value is not empty
    for key in ["runtime", "gpu", "display", "audio"]:
        saved_value = saved.get(key, "")
        if saved_value and saved_value.strip():
            merged[key] = saved_value

    # Java isn't detected; it comes from the saved config or the default.
    merged["java"] = normalize_java(saved.get("java"))
    merged["memory"] = normalize_memory(saved.get("memory"))

    # Add auto_xhost setting
    merged["auto_xhost"] = saved.get("auto_xhost", True)

    return merged


def get_config_path() -> Path:
    """
    Get the configuration file path.

    Returns:
        Path: Path to config file
    """
    return CONFIG_FILE


def config_exists() -> bool:
    """
    Check if configuration file exists.

    Returns:
        bool: True if config file exists
    """
    return CONFIG_FILE.exists()


def reset_config() -> bool:
    """
    Delete the configuration file.

    Returns:
        bool: True if successful or file didn't exist
    """
    try:
        if CONFIG_FILE.exists():
            CONFIG_FILE.unlink()
        return True
    except Exception as e:
        print(f"Error: Could not delete config file: {e}")
        return False


def create_default_config() -> Dict[str, any]:
    """
    Create a default configuration template.

    Returns:
        dict: Default configuration
    """
    return {
        "runtime": "",  # Empty means auto-detect
        "gpu": "",
        "display": "",
        "audio": "",
        "auto_xhost": True,
    }
