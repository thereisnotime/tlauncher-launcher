"""
CLI interface for Minecraft Launcher.
Provides terminal-based interaction with rich formatting.
"""
import sys
from typing import Dict

# Try importing rich libraries with fallback
try:
    from rich.console import Console
    from rich.table import Table
    from rich.panel import Panel
    RICH_AVAILABLE = True
except ImportError:
    RICH_AVAILABLE = False

try:
    import questionary
    QUESTIONARY_AVAILABLE = True
except ImportError:
    QUESTIONARY_AVAILABLE = False

from core.detector import detect_system, get_detection_details
from core.config import load_config, save_config, merge_config, reset_config
from core.validator import validate_system, run_xhost_if_needed
from core.container import ContainerManager
from core.composer import get_command_preview


def run_cli(args):
    """
    Main CLI entry point.

    Args:
        args: Parsed command-line arguments from argparse
    """
    # Handle different commands
    if args.command == 'doctor':
        run_doctor(args)
    elif args.command == 'status':
        run_status(args)
    elif args.command == 'stop':
        run_stop(args)
    elif args.command == 'logs':
        run_logs(args)
    elif args.command == 'restart':
        run_restart(args)
    elif args.command == 'start':
        run_start(args)
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
        saved['runtime'] = args.runtime
    if args.gpu:
        saved['gpu'] = args.gpu
    if args.display:
        saved['display'] = args.display
    if args.audio:
        saved['audio'] = args.audio

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

    # Step 8: Run xhost if needed
    if config['display'] == 'x11' and config.get('auto_xhost', True):
        _print(console, "[yellow]Setting X11 permissions...[/yellow]")
        if run_xhost_if_needed(config):
            _print(console, "[green]✓ X11 permissions set[/green]")
        else:
            _print(console, "[yellow]⚠ Could not set X11 permissions automatically[/yellow]")

    # Step 9: Start container
    _print(console, "\n[green]Starting Minecraft...[/green]")
    _print(console, f"[dim]Command: {get_command_preview(config, 'up')}[/dim]\n")

    manager = ContainerManager(config)

    def output_handler(line):
        print(line)

    success = manager.start(
        detached=args.detached,
        force_recreate=getattr(args, 'force_recreate', False),
        output_callback=output_handler
    )

    if success:
        if args.detached:
            _print(console, "\n[green]✓ Container started in background[/green]")
            _print(console, f"View logs: {sys.argv[0]} --no-gui logs -f")
        else:
            _print(console, "\n[green]✓ Container stopped[/green]")
    else:
        _print(console, "\n[red]✗ Failed to start container[/red]")
        sys.exit(1)


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
        for line in manager.logs(follow=getattr(args, 'follow', False)):
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

    if status['running']:
        _print(console, "[green]✓ Container is running[/green]")
    else:
        _print(console, "[yellow]Container is not running[/yellow]")

    if status.get('output'):
        print("\n" + status['output'])


def run_doctor(args):
    """Handle 'doctor' command - system validation."""
    console = Console() if RICH_AVAILABLE else None

    _print(console, "[bold]Minecraft Launcher - System Check[/bold]\n")

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


def _show_configuration(console, config: Dict, detected: Dict, saved: Dict):
    """Display configuration table."""
    if not RICH_AVAILABLE:
        print("\nConfiguration:")
        for key, value in config.items():
            if key == 'auto_xhost':
                continue
            source = " (saved)" if saved.get(key) else " (detected)"
            print(f"  {key.capitalize()}: {value}{source}")
        return

    table = Table(title="System Configuration")
    table.add_column("Setting", style="cyan")
    table.add_column("Value", style="green")
    table.add_column("Source", style="dim")

    for key in ['runtime', 'gpu', 'display', 'audio']:
        value = config[key]
        source = "saved" if saved.get(key) and saved[key] == value else "detected"
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


def _show_doctor_detection(console, details: Dict):
    """Show detailed detection results for doctor command."""
    _print(console, "[bold]Detection Results:[/bold]")

    # Runtime
    rt = details['runtime']
    status = "✓" if rt['available'] else "✗"
    _print(console, f"{status} Runtime: {rt['value']} ({rt['path']})")

    # GPU
    gpu = details['gpu']
    status = "✓" if gpu['devices_exist'] else "⚠"
    _print(console, f"{status} GPU: {gpu['details']}")

    # Display
    disp = details['display']
    _print(console, f"✓ Display: {disp['value']} (session: {disp['session_type']}, var: {disp['display_var']})")

    # Audio
    aud = details['audio']
    _print(console, f"  Audio: {aud['details']}")


def _confirm_start(console, config: Dict) -> bool:
    """Ask user to confirm start."""
    if QUESTIONARY_AVAILABLE:
        return questionary.confirm("Start Minecraft with these settings?", default=True).ask()
    else:
        # Fallback to simple input
        response = input("\nStart Minecraft with these settings? [Y/n] ")
        return response.lower() in ['', 'y', 'yes']


def _print(console, text: str):
    """Print with rich if available, plain otherwise."""
    if console:
        console.print(text)
    else:
        # Strip rich markup for plain printing
        import re
        plain_text = re.sub(r'\[.*?\]', '', text)
        print(plain_text)
