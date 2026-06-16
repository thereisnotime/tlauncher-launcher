"""
Compose command builder for Minecraft Launcher.
Constructs docker/podman compose commands with appropriate file combinations.
"""

import os
from pathlib import Path
from typing import Dict, List

from .detector import detect_compose_provider, detect_ui_scale


def build_compose_env(config: Dict[str, str]) -> Dict[str, str]:
    """
    Build the environment for compose subprocess calls.

    Forces a modern Docker Compose v2 provider for podman (so it does not fall
    back to the legacy python `podman-compose`) and injects the detected HiDPI
    scale for the TLauncher GUI. Pre-existing values in the environment are
    respected, so users can override either by exporting them manually.

    Args:
        config: Configuration dict with runtime, gpu, display, audio

    Returns:
        dict: Environment mapping to pass to subprocess calls
    """
    env = os.environ.copy()

    # Avoid the legacy python podman-compose by pointing podman at a v2 provider.
    if config.get("runtime") == "podman" and not env.get("PODMAN_COMPOSE_PROVIDER"):
        provider = detect_compose_provider("podman")
        if provider:
            env["PODMAN_COMPOSE_PROVIDER"] = provider

    # Scale the TLauncher Swing GUI to match the host display (QHD/HiDPI).
    if not env.get("JAVA_UI_SCALE"):
        scale = detect_ui_scale()
        if scale > 1.0:
            env["JAVA_UI_SCALE"] = f"{scale:g}"

    return env


def build_compose_command(
    config: Dict[str, str], action: str, extra_args: List[str] = None
) -> List[str]:
    """
    Build compose command with correct file order.

    Args:
        config: Configuration dict with runtime, gpu, display, audio
        action: Compose action (up, down, logs, ps, etc.)
        extra_args: Additional arguments to append (e.g., ['-d', '--force-recreate'])

    Returns:
        list: Complete command as list of strings
    """
    # Get the directory where compose files are located
    compose_dir = get_compose_directory()

    # Build list of compose files in correct order
    files = [
        "compose.base.yaml",
        f"compose.{config['runtime']}.yaml",
        f"compose.{config['gpu']}.yaml",
        f"compose.{config['display']}.yaml",
        f"compose.audio-{config['audio']}.yaml",
    ]

    # Start building command
    cmd = [config["runtime"], "compose"]

    # Add compose files
    for f in files:
        cmd.extend(["-f", str(compose_dir / f)])

    # Add action
    cmd.append(action)

    # Add extra arguments if provided
    if extra_args:
        cmd.extend(extra_args)

    return cmd


def get_compose_directory() -> Path:
    """
    Get the directory containing compose files.

    Returns:
        Path: Directory path
    """
    # Assume compose files are in the same directory as this script's parent
    # core/composer.py -> core/ -> parent directory
    return Path(__file__).parent.parent


def get_compose_files(config: Dict[str, str]) -> List[str]:
    """
    Get list of compose files that will be used.

    Args:
        config: Configuration dict

    Returns:
        list: List of compose file names
    """
    return [
        "compose.base.yaml",
        f"compose.{config['runtime']}.yaml",
        f"compose.{config['gpu']}.yaml",
        f"compose.{config['display']}.yaml",
        f"compose.audio-{config['audio']}.yaml",
    ]


def validate_compose_files_exist(config: Dict[str, str]) -> tuple[bool, List[str]]:
    """
    Check if all required compose files exist.

    Args:
        config: Configuration dict

    Returns:
        tuple: (all_exist, missing_files)
    """
    compose_dir = get_compose_directory()
    files = get_compose_files(config)
    missing = []

    for f in files:
        if not (compose_dir / f).exists():
            missing.append(f)

    return len(missing) == 0, missing


def get_command_preview(config: Dict[str, str], action: str = "up") -> str:
    """
    Get human-readable preview of the command that will be run.

    Args:
        config: Configuration dict
        action: Compose action

    Returns:
        str: Command preview
    """
    cmd = build_compose_command(config, action)
    return " ".join(cmd)
