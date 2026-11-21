"""
CLI interface for Craftainer.
Provides terminal-based interaction with rich formatting.
"""

import sys

# Try importing rich libraries with fallback
try:
    from rich.console import Console
    from rich.table import Table

    RICH_AVAILABLE = True
except ImportError:
    RICH_AVAILABLE = False

try:
    import questionary

    QUESTIONARY_AVAILABLE = True
except ImportError:
    QUESTIONARY_AVAILABLE = False

from core.composer import get_command_preview
from core.config import load_config, merge_config
from core.container import ContainerManager, build_image_command, image_exists, image_tag
from core.detector import detect_system, get_detection_details
from core.log_analyzer import analyze_lines
from core.validator import run_xhost_if_needed, validate_system


def run_cli(args):
    """
    Main CLI entry point.

    Args:
        args: Parsed command-line arguments from argparse
    """
    # Handle different commands
    if args.command == "doctor":
        run_doctor(args)
    elif args.command == "status":
        run_status(args)
    elif args.command == "stop":
        run_stop(args)
    elif args.command == "logs":
        run_logs(args)
    elif args.command == "restart":
        run_restart(args)
    elif args.command == "stats":
        run_stats(args)
    elif args.command == "profiles":
        run_profiles(args)
    elif args.command == "start":
        run_start(args)
    elif args.command == "game-ram":
        run_game_ram(args)
    elif args.command == "install-compose":
        run_install_compose(args)
    else:
        print(f"Unknown command: {args.command}")
        sys.exit(1)


def run_start(args):
    """Handle 'start' command."""
    console = Console() if RICH_AVAILABLE else None

    # Step 1: Detect system
    _print(console, "[yellow]Detecting system configuration...[/yellow]")
    detected = detect_system()

    # Step 2: Load saved config
    saved = load_config()

    # Step 3: Apply command-line overrides
    if args.runtime:
        saved["runtime"] = args.runtime
    if args.gpu:
        saved["gpu"] = args.gpu
    if args.display:
        saved["display"] = args.display
    if args.audio:
        saved["audio"] = args.audio
    if getattr(args, "java", None):
        saved["java"] = args.java
    if getattr(args, "memory", None):
        saved["memory"] = args.memory

    # Step 4: Merge configurations
    config = merge_config(detected, saved)

    # Step 5: Show configuration
    _show_configuration(console, config, detected, saved)

    # Step 6: Confirm (unless --yes)
    if not args.yes:
        if not _confirm_start(console, config):
            _print(console, "Cancelled.")
            return

    # Step 7: Validate system
    _print(console, "\n[yellow]Validating system...[/yellow]")
    valid, issues = validate_system(config)

    if issues:
        _show_validation_issues(console, issues)

    if not valid:
        _print(console, "[red]✗ System validation failed. Cannot start.[/red]")
        sys.exit(1)

    # Build the image automatically if it's missing (first run). The manual
    # 'just build' is only needed to pick up Containerfile changes.
    runtime = config.get("runtime", "podman")
    if not image_exists(runtime, config["java"]):
        _print(
            console,
            f"[yellow]Image {image_tag(config['java'])} not found — building it first "
            "(one time)...[/yellow]",
        )
        if not _build_image(console, runtime, config["java"]):
            _print(console, "[red]✗ Image build failed. Cannot start.[/red]")
            sys.exit(1)

    # Step 8: Run xhost if needed (x11 and XWayland both use the X server)
    if config["display"] in ("x11", "wayland") and config.get("auto_xhost", True):
        _print(console, "[yellow]Setting X11 permissions...[/yellow]")
        if run_xhost_if_needed(config):
            _print(console, "[green]✓ X11 permissions set[/green]")
        else:
            _print(console, "[yellow]⚠ Could not set X11 permissions automatically[/yellow]")

    # Step 9: Start container
    _print(console, "\n[green]Starting Minecraft...[/green]")
    _print(console, f"[dim]Command: {get_command_preview(config, 'up')}[/dim]\n")

    manager = ContainerManager(config)

    collected_lines = []

    def output_handler(line):
        print(line)
        collected_lines.append(line)

    success = manager.start(
        detached=args.detached,
        force_recreate=getattr(args, "force_recreate", False),
        output_callback=output_handler,
    )

    if success:
        if args.detached:
            _print(console, "\n[green]✓ Container started in background[/green]")
            _print(console, f"View logs: {sys.argv[0]} --no-gui logs -f")
        else:
            _print(console, "\n[green]✓ Container stopped[/green]")
    else:
        _print(console, "\n[red]✗ Container exited with error[/red]")

    if not args.detached:
        _show_log_findings(console, collected_lines)

    if not success:
        sys.exit(1)


def _build_image(console, runtime: str, java: str) -> bool:
    """Build the container image, streaming output. Returns True on success."""
    import subprocess
    from pathlib import Path

    repo_dir = str(Path(__file__).parent)
    try:
        proc = subprocess.Popen(
            build_image_command(runtime, java),
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            cwd=repo_dir,
        )
        for line in proc.stdout:
            print(line.rstrip())
        proc.wait()
        if proc.returncode == 0:
            _print(console, "[green]✓ Image built[/green]")
            return True
        return False
    except FileNotFoundError:
        _print(console, f"[red]'{runtime}' not found — is it installed?[/red]")
        return False
    except Exception as e:
        _print(console, f"[red]Build error: {e}[/red]")
        return False


def run_stop(args):
    """Handle 'stop' command."""
    console = Console() if RICH_AVAILABLE else None

    # Use current/saved config to know which runtime to use
    saved = load_config()
    detected = detect_system()
    config = merge_config(detected, saved)

    _print(console, "[yellow]Stopping container...[/yellow]")

    manager = ContainerManager(config)
    if manager.stop():
        _print(console, "[green]✓ Container stopped[/green]")
    else:
        _print(console, "[red]✗ Failed to stop container[/red]")
        sys.exit(1)


def run_restart(args):
    """Handle 'restart' command."""
    console = Console() if RICH_AVAILABLE else None

    saved = load_config()
    detected = detect_system()
    config = merge_config(detected, saved)

    _print(console, "[yellow]Restarting container...[/yellow]")

    manager = ContainerManager(config)

    def output_handler(line):
        print(line)

    if manager.restart(output_callback=output_handler):
        _print(console, "[green]✓ Container restarted[/green]")
    else:
        _print(console, "[red]✗ Failed to restart container[/red]")
        sys.exit(1)


def run_logs(args):
    """Handle 'logs' command."""
    saved = load_config()
    detected = detect_system()
    config = merge_config(detected, saved)

    manager = ContainerManager(config)

    try:
        for line in manager.logs(follow=getattr(args, "follow", False)):
            print(line)
    except KeyboardInterrupt:
        pass


def run_status(args):
    """Handle 'status' command."""
    console = Console() if RICH_AVAILABLE else None

    saved = load_config()
    detected = detect_system()
    config = merge_config(detected, saved)

    manager = ContainerManager(config)
    status = manager.status()

    if status["running"]:
        _print(console, "[green]✓ Container is running[/green]")
    else:
        _print(console, "[yellow]Container is not running[/yellow]")

    if status.get("output"):
        print("\n" + status["output"])


def run_doctor(args):
    """Handle 'doctor' command - system validation."""
    console = Console() if RICH_AVAILABLE else None

    from core.version import version_string

    _print(console, "[bold]Craftainer - System Check[/bold]")
    _print(console, f"Launcher version: {version_string()}\n")

    # Detect system
    detected = detect_system()
    details = get_detection_details()
    saved = load_config()
    config = merge_config(detected, saved)

    # Show detection results
    _show_doctor_detection(console, details)

    # Validate
    _print(console, "\n[bold]Validation:[/bold]")
    valid, issues = validate_system(config)

    if issues:
        _show_validation_issues(console, issues)
    else:
        _print(console, "[green]✓ No issues found[/green]")

    if valid:
        _print(console, "\n[green bold]✓ System ready![/green bold]")
    else:
        _print(console, "\n[red bold]✗ System has errors[/red bold]")
        sys.exit(1)


def run_game_ram(args):
    """Show or set Minecraft's RAM (TLauncher's minecraft.memory.ram3)."""
    from core.config import load_config, merge_config
    from core.detector import detect_system
    from core.game_ram import get_game_ram, max_game_ram, mem_limit_mb, set_game_ram

    console = Console() if RICH_AVAILABLE else None
    config = merge_config(detect_system(), load_config())
    cap = mem_limit_mb(config["memory"])
    current = get_game_ram()
    value = args.profile_action

    if not value:
        shown = f"{current} MB" if current else "not set yet (start TLauncher once)"
        _print(console, f"Minecraft RAM: {shown}")
        _print(console, f"Container cap: {cap} MB (max sensible game RAM: {max_game_ram(cap)} MB)")
        return
    if not str(value).isdigit():
        _print(console, "[red]Usage: game-ram [MB], e.g. game-ram 4096[/red]")
        sys.exit(1)
    mb = int(value)
    if mb > max_game_ram(cap):
        _print(
            console,
            f"[red]{mb} MB won't fit in the {cap} MB container cap; use at most "
            f"{max_game_ram(cap)} MB or raise --memory[/red]",
        )
        sys.exit(1)
    if _tlauncher_running(config.get("runtime", "podman")):
        _print(
            console, "[red]Stop Minecraft first; TLauncher overwrites its settings on exit[/red]"
        )
        sys.exit(1)
    set_game_ram(mb)
    _print(console, f"[green]✓ Minecraft RAM set to {mb} MB[/green]")


def _tlauncher_running(runtime: str) -> bool:
    import subprocess

    try:
        out = subprocess.run(
            [runtime, "ps", "--filter", "name=^tlauncher$", "--format", "{{.Names}}"],
            capture_output=True,
            text=True,
            timeout=10,
        ).stdout
    except (OSError, subprocess.SubprocessError):
        return False
    return "tlauncher" in out.split()


def run_install_compose(args):
    """Handle 'install-compose' - fetch Docker Compose v2 into ~/.local/bin."""
    from core.compose_installer import default_target, install_docker_compose

    console = Console() if RICH_AVAILABLE else None
    target = default_target()

    if not args.yes:
        prompt = f"Download Docker Compose v2 to {target}?"
        if QUESTIONARY_AVAILABLE:
            ok = questionary.confirm(prompt, default=True).ask()
        else:
            ok = input(f"{prompt} [Y/n] ").lower() in ["", "y", "yes"]
        if not ok:
            _print(console, "Cancelled.")
            return

    result = install_docker_compose(target, log=print)
    if result.ok:
        _print(console, f"[green]✓ {result.message}[/green]")
    else:
        _print(console, f"[red]✗ {result.message}[/red]")
        sys.exit(1)


def run_stats(args):
    """Handle 'stats' command - show resource usage."""
    import json
    import subprocess
    import time

    console = Console() if RICH_AVAILABLE else None

    # Get runtime
    saved = load_config()
    detected = detect_system()
    config = merge_config(detected, saved)
    runtime = config.get("runtime", "podman")

    _print(console, "[bold]Resource Usage Monitor[/bold]\n")
    _print(console, "Press Ctrl+C to exit\n")

    try:
        while True:
            # Get container stats
            result = subprocess.run(
                [
                    runtime,
                    "stats",
                    "--no-stream",
                    "--format",
                    "json" if runtime == "podman" else "table",
                    "tlauncher",
                ],
                capture_output=True,
                text=True,
                timeout=3,
            )

            if result.returncode != 0 or not result.stdout.strip():
                _print(console, "[yellow]Container not running[/yellow]")
                return

            # Parse stats
            if RICH_AVAILABLE:
                table = Table(title="Container Resources")
                table.add_column("Metric", style="cyan")
                table.add_column("Value", style="green")

                if runtime == "podman":
                    stats_list = json.loads(result.stdout.strip())
                    stats = stats_list[0] if isinstance(stats_list, list) else stats_list

                    table.add_row("CPU", stats.get("cpu_percent", "--"))
                    table.add_row("Memory", stats.get("mem_usage", "--").split("/")[0].strip())
                    table.add_row("Network In", stats.get("net_io", "--").split("/")[0].strip())
                    table.add_row(
                        "Network Out",
                        stats.get("net_io", "--").split("/")[1].strip()
                        if "/" in stats.get("net_io", "")
                        else "--",
                    )
                else:
                    # Docker table format
                    lines = result.stdout.strip().split("\n")
                    data_line = lines[-1] if lines else ""
                    import re

                    parts = re.split(r"\s{2,}", data_line.strip())

                    if len(parts) >= 6:
                        table.add_row("CPU", parts[2])
                        table.add_row("Memory", parts[3].split("/")[0].strip())
                        table.add_row(
                            "Network In",
                            parts[5].split("/")[0].strip() if "/" in parts[5] else "--",
                        )
                        table.add_row(
                            "Network Out",
                            parts[5].split("/")[1].strip() if "/" in parts[5] else "--",
                        )

                # GPU stats (NVIDIA only)
                if config.get("gpu") == "nvidia":
                    try:
                        gpu_result = subprocess.run(
                            [
                                "nvidia-smi",
                                "--query-gpu=utilization.gpu",
                                "--format=csv,noheader,nounits",
                            ],
                            capture_output=True,
                            text=True,
                            timeout=1,
                        )
                        if gpu_result.returncode == 0:
                            table.add_row("GPU", f"{gpu_result.stdout.strip()}%")
                    except FileNotFoundError:
                        pass

                console.print(table)
            else:
                # Plain text output
                print(result.stdout)

            # One-shot mode if not in interactive terminal
            if not sys.stdout.isatty():
                break

            time.sleep(2)
            if RICH_AVAILABLE:
                console.clear()

    except KeyboardInterrupt:
        _print(console, "\n[yellow]Stopped monitoring[/yellow]")


def run_profiles(args):
    """Handle 'profiles' command - profile management."""

    console = Console() if RICH_AVAILABLE else None

    action = args.profile_action
    profile_arg = args.profile_arg

    if not action or action == "list":
        # List all profiles
        _profiles_list(console)
    elif action == "export":
        # Export profile
        if not profile_arg:
            _print(console, "[red]Error: Profile name required[/red]")
            _print(console, "Usage: profiles export <profile-name>")
            sys.exit(1)
        _profiles_export(console, profile_arg)
    elif action == "import":
        # Import profile
        if not profile_arg:
            _print(console, "[red]Error: file path or URL required[/red]")
            _print(console, "Usage: profiles import <file-or-url> [--into <version>]")
            sys.exit(1)
        _profiles_import(console, profile_arg, getattr(args, "into", None))
    elif action == "update":
        _profiles_update(console, profile_arg)
    elif action == "delete":
        # Delete profile
        if not profile_arg:
            _print(console, "[red]Error: Profile name required[/red]")
            _print(console, "Usage: profiles delete <profile-name>")
            sys.exit(1)
        _profiles_delete(console, profile_arg)
    else:
        _print(console, f"[red]Unknown profile action: {action}[/red]")
        _print(console, "Available actions: list, export, import, delete")
        sys.exit(1)


def _profiles_list(console):
    """List all Minecraft profiles."""
    import json
    from pathlib import Path

    profiles_file = Path(__file__).parent / "home" / "launcher_profiles.json"

    if not profiles_file.exists():
        _print(console, "[yellow]No profiles found[/yellow]")
        return

    with open(profiles_file) as f:
        data = json.load(f)

    profiles = data.get("profiles", {})
    if not profiles:
        _print(console, "[yellow]No profiles found[/yellow]")
        return

    _print(console, "[bold]Minecraft Profiles:[/bold]\n")

    if RICH_AVAILABLE:
        table = Table()
        table.add_column("Name", style="cyan")
        table.add_column("Version", style="green")
        table.add_column("Type", style="yellow")
        table.add_column("Selected", style="magenta")

        selected_profile = data.get("selectedProfile")
        for profile_id, profile_data in profiles.items():
            name = profile_data.get("name", profile_id)
            version = profile_data.get("lastVersionId", "unknown")
            profile_type = profile_data.get("type", "custom")
            is_selected = "✓" if name == selected_profile or profile_id == selected_profile else ""

            table.add_row(name, version, profile_type, is_selected)

        console.print(table)
    else:
        selected_profile = data.get("selectedProfile")
        for profile_id, profile_data in profiles.items():
            name = profile_data.get("name", profile_id)
            version = profile_data.get("lastVersionId", "unknown")
            profile_type = profile_data.get("type", "custom")
            is_selected = (
                " [SELECTED]" if name == selected_profile or profile_id == selected_profile else ""
            )
            print(f"  {name} (v{version}) [{profile_type}]{is_selected}")


def _find_profile_id(profile_name: str):
    """Return (profile_id, profiles) for a profile name or id, or exit with a list."""
    import json
    from pathlib import Path

    profiles_file = Path(__file__).parent / "home" / "launcher_profiles.json"
    if not profiles_file.exists():
        print("Error: No profiles found")
        sys.exit(1)
    with open(profiles_file) as f:
        profiles = json.load(f).get("profiles", {})
    for pid, pdata in profiles.items():
        if pdata.get("name") == profile_name or pid == profile_name:
            return pid, profiles
    print(f"Error: Profile '{profile_name}' not found. Available profiles:")
    for pid, pdata in profiles.items():
        print(f"  - {pdata.get('name', pid)}")
    sys.exit(1)


def _profiles_export(console, profile_name: str):
    """Export a profile (version files + its mods/configs) to a .mcprofile.zip."""
    from pathlib import Path

    from core.packs import PackError, export_profile

    profile_id, profiles = _find_profile_id(profile_name)
    version_id = profiles[profile_id].get("lastVersionId", "unknown")
    output_file = f"{profile_name}_{version_id}.mcprofile.zip".replace("/", "_")

    _print(console, f"[yellow]Exporting profile: {profile_name}[/yellow]")
    try:
        export_profile(profile_id, Path(output_file), log=print)
    except PackError as e:
        _print(console, f"[red]✗ Export failed: {e}[/red]")
        sys.exit(1)
    _print(console, f"[green]✓ Exported to: {output_file}[/green]")


def _profiles_update(console, name=None):
    """Re-import modpacks whose source (URL or file) changed since they were installed."""
    from core.packs import PackError, check_pack_update, list_installed_packs

    packs = [p for p in list_installed_packs() if not name or p.name == name]
    if not packs:
        _print(console, "No imported modpacks" + (f" named '{name}'" if name else ""))
        return
    for pack in packs:
        label = f"{pack.name} {pack.version}".strip()
        try:
            new = check_pack_update(pack)
        except PackError as e:
            _print(console, f"[yellow]⚠ {label}: {e}[/yellow]")
            continue
        if not new:
            _print(console, f"✓ {label} is up to date")
            continue
        _print(console, f"[yellow]⬆ {label} -> {new}[/yellow]")
        _profiles_import(console, pack.source)


def _profiles_import(console, source: str, target_version=None):
    """Import a .mrpack, .mcprofile.zip or mods .zip from a path or URL."""
    from core.config import load_config, merge_config
    from core.container import image_exists, image_tag
    from core.detector import detect_system
    from core.packs import PackError, import_archive

    config = merge_config(detect_system(), load_config())
    runtime, java = config.get("runtime", "podman"), config["java"]

    def ensure_image():
        # Forge/NeoForge installers run inside the launcher image.
        if not image_exists(runtime, java):
            _print(console, f"[yellow]Building {image_tag(java)} first (one time)...[/yellow]")
            if not _build_image(console, runtime, java):
                raise PackError("Image build failed")

    try:
        ensure_image()
        result = import_archive(
            source,
            runtime=runtime,
            image=image_tag(java),
            log=print,
            # Plain mod zips go to the shared mods folder unless --into is given.
            target_version=target_version or "",
        )
    except PackError as e:
        _print(console, f"[red]✗ Import failed: {e}[/red]")
        sys.exit(1)

    _print(console, f"[green]✓ Imported {result.name} ({result.files} files)[/green]")
    for note in result.notes:
        _print(console, f"  {note}")
    if result.kind == "mrpack":
        _print(console, f"  Pick [bold]{result.version_id}[/bold] in TLauncher and play.")
        from core.game_ram import get_game_ram, mem_limit_mb, suggest_for_modpack

        mods = sum(1 for _ in (result.game_dir / "mods").glob("*.jar"))
        ram = suggest_for_modpack(get_game_ram(), mem_limit_mb(config["memory"]), mods)
        if ram:
            _print(console, f"  Tip: give Minecraft {ram} MB:  ./minecraft.py game-ram {ram}")


def _profiles_delete(console, profile_name: str):
    """Delete a profile."""
    import json
    from pathlib import Path

    profiles_file = Path(__file__).parent / "home" / "launcher_profiles.json"

    if not profiles_file.exists():
        _print(console, "[red]Error: No profiles found[/red]")
        sys.exit(1)

    with open(profiles_file) as f:
        data = json.load(f)

    profiles = data.get("profiles", {})

    # Find profile by name
    profile_id = None
    profile_data = None

    for pid, pdata in profiles.items():
        if pdata.get("name") == profile_name or pid == profile_name:
            profile_id = pid
            profile_data = pdata
            break

    if not profile_data:
        _print(console, f"[red]Error: Profile '{profile_name}' not found[/red]")
        sys.exit(1)

    # Confirm deletion
    _print(console, f"[yellow]Delete profile '{profile_name}'?[/yellow]")
    _print(console, "[dim]This will remove the profile entry from TLauncher.[/dim]")
    _print(console, "[dim]Version files will NOT be deleted.[/dim]")

    if QUESTIONARY_AVAILABLE:
        confirmed = questionary.confirm("Proceed?", default=False).ask()
    else:
        response = input("\nProceed? [y/N] ")
        confirmed = response.lower() in ["y", "yes"]

    if not confirmed:
        _print(console, "Cancelled")
        return

    # Remove from profiles
    del profiles[profile_id]

    # Update selected profile if needed
    if data.get("selectedProfile") == profile_id:
        if profiles:
            data["selectedProfile"] = list(profiles.keys())[0]
        else:
            data["selectedProfile"] = None

    # Save
    with open(profiles_file, "w") as f:
        json.dump(data, f, indent=2)

    _print(console, f"[green]✓ Profile '{profile_name}' deleted[/green]")


def _show_configuration(console, config: dict, detected: dict, saved: dict):
    """Display configuration table."""
    if not RICH_AVAILABLE:
        print("\nConfiguration:")
        for key, value in config.items():
            if key == "auto_xhost":
                continue
            fallback = " (default)" if key in ("java", "memory") else " (detected)"
            source = " (saved)" if saved.get(key) else fallback
            print(f"  {key.capitalize()}: {value}{source}")
        return

    table = Table(title="System Configuration")
    table.add_column("Setting", style="cyan")
    table.add_column("Value", style="green")
    table.add_column("Source", style="dim")

    for key in ["runtime", "gpu", "display", "audio", "java", "memory"]:
        value = config[key]
        fallback = "default" if key in ("java", "memory") else "detected"
        source = "saved" if saved.get(key) and saved[key] == value else fallback
        table.add_row(key.capitalize(), value, source)

    console.print(table)


def _show_validation_issues(console, issues):
    """Display validation issues."""
    for issue in issues:
        symbol = "✗" if issue.is_blocking() else "⚠"
        color = "red" if issue.is_blocking() else "yellow"

        _print(console, f"[{color}]{symbol} {issue.message}[/{color}]")

        if issue.fix_hint:
            _print(console, f"  [dim]→ {issue.fix_hint}[/dim]")


def _show_doctor_detection(console, details: dict):
    """Show detailed detection results for doctor command."""
    _print(console, "[bold]Detection Results:[/bold]")

    # Runtime
    rt = details["runtime"]
    status = "✓" if rt["available"] else "✗"
    _print(console, f"{status} Runtime: {rt['value']} ({rt['path']})")

    # GPU
    gpu = details["gpu"]
    status = "✓" if gpu["devices_exist"] else "⚠"
    _print(console, f"{status} GPU: {gpu['details']}")

    # Display
    disp = details["display"]
    resolution = disp.get("resolution") or "unknown"
    _print(
        console,
        f"✓ Display: {disp['value']} ({resolution}, session: {disp['session_type']}, "
        f"var: {disp['display_var']})",
    )

    # Audio
    aud = details["audio"]
    audio_status = "✓" if aud["value"] != "none" else "⚠"
    _print(console, f"{audio_status} Audio: {aud['details']}")

    # Host display scale (informational only - not auto-applied; TLauncher
    # ignores Java2D scaling. Export JAVA_UI_SCALE to force it.)
    scale = details["ui_scale"]["value"]
    if scale > 1.0:
        _print(console, f"  Host scale: {scale:g}x (not applied; export JAVA_UI_SCALE to force)")
    else:
        _print(console, "  Host scale: 1x")


def _confirm_start(console, config: dict) -> bool:
    """Ask user to confirm start."""
    if QUESTIONARY_AVAILABLE:
        return bool(questionary.confirm("Start Minecraft with these settings?", default=True).ask())
    # Fallback to simple input
    response = input("\nStart Minecraft with these settings? [Y/n] ")
    return response.lower() in ["", "y", "yes"]


def _show_log_findings(console, lines):
    """Analyze log lines and print findings if any."""
    findings = analyze_lines(lines)
    if not findings:
        return

    _print(console, "\n[bold]Log Analysis:[/bold]")
    _print(console, "─" * 50)

    for finding in findings:
        color = "red" if finding.level == "error" else "yellow"
        symbol = "✗" if finding.level == "error" else "⚠"
        _print(console, f"[{color}]{symbol} {finding.title}[/{color}]")
        _print(console, f"  [dim]{finding.detail}[/dim]")
        for rec_line in finding.recommendation.splitlines():
            _print(console, f"  [cyan]→ {rec_line}[/cyan]")
        _print(console, "")


def _print(console, text: str):
    """Print with rich if available, plain otherwise."""
    if console:
        console.print(text)
    else:
        # Strip rich markup for plain printing
        import re

        plain_text = re.sub(r"\[.*?\]", "", text)
        print(plain_text)
