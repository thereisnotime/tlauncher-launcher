# Minecraft Launcher - Wrapper Structure

This document explains the architecture of the Python launcher wrapper that provides GUI and CLI interfaces for the containerized Minecraft setup.

---

## Architecture Overview

The launcher uses a modular architecture with three layers:

```
┌─────────────────────────────────────────┐
│        minecraft.py (Entry Point)       │
│  Decides: GUI mode or CLI mode?         │
└─────────────┬───────────────────────────┘
              │
      ┌───────┴───────┐
      │               │
      ▼               ▼
┌──────────┐    ┌──────────┐
│  gui.py  │    │  cli.py  │
│ (Tkinter)│    │ (Rich)   │
└─────┬────┘    └────┬─────┘
      │              │
      └──────┬───────┘
             │
             ▼
    ┌────────────────┐
    │   core/        │
    │   (Backend)    │
    └────────────────┘
```

---

## File Structure

```
.
├── minecraft.py                  # Main entry point (~200 lines)
├── minecraft                     # Symlink to minecraft.py
├── minecraft.desktop             # Desktop application launcher
│
├── gui.py                        # GUI entry: MinecraftLauncherGUI (~110 lines)
├── cli.py                        # CLI interface (~780 lines)
│
├── ui/                           # GUI feature modules, one mixin each (~2,600 lines)
│   ├── __init__.py              # Package docstring
│   ├── common.py                # APP_DIR (repo root) and APP_VERSION
│   ├── base.py                  # GUIBase: typed declarations of the shared self (mypy only)
│   ├── theme.py                 # ThemeMixin: ttk styles, self.colors, window icon
│   ├── layout.py                # LayoutMixin: main window widgets (_create_widgets)
│   ├── console.py               # ConsoleMixin: log(), clear/copy logs, status label
│   ├── settings.py              # SettingsMixin: detection, dropdowns, save/edit config
│   ├── state.py                 # ContainerStateMixin: runtime/container polling, button sync
│   ├── container_control.py     # ContainerControlMixin: start/stop/restart/rebuild, Compose v2 offer
│   ├── doctor.py                # DoctorMixin: Doctor and Report Bug
│   ├── updates.py               # UpdatesMixin: update banner and git pull
│   ├── monitor.py               # ResourceMonitorMixin: container stats panel
│   ├── profiles.py              # ProfilesMixin: profiles list, export, delete, folder, help
│   ├── profile_import.py        # ProfileImportMixin: import from file/URL, mods-target dialog
│   └── profile_info.py          # ProfileInfoMixin: Info window and Copy Info
│
├── core/                         # Shared backend modules (~2,600 lines)
│   ├── __init__.py              # Package initialization
│   ├── detector.py              # System auto-detection
│   ├── config.py                # Configuration management
│   ├── composer.py              # Compose command builder
│   ├── validator.py             # Pre-flight validation
│   ├── container.py             # Container lifecycle
│   ├── packs.py                 # Profile/modpack import and export
│   ├── compose_installer.py     # Docker Compose v2 downloader
│   └── log_analyzer.py          # Post-exit log analysis
│
├── requirements.txt              # Python dependencies
├── compose.*.yaml                # Docker/Podman compose files
├── Containerfile                 # Container image definition
└── entrypoint.sh                 # Container startup script
```

---

## Component Breakdown

### 1. Entry Point (`minecraft.py`)

**Purpose:** Determine which interface to use and dispatch.

**Decision Logic:**
```python
if '--no-gui' in args:
    → CLI mode
elif len(sys.argv) > 1:
    → CLI mode (has arguments)
elif DISPLAY available and tkinter available:
    → GUI mode
else:
    → CLI mode (fallback)
```

**Responsibilities:**
- Parse mode selection
- Import appropriate interface
- Handle launch errors

---

### 2. GUI Interface (`gui.py` + `ui/`)

**Framework:** Tkinter (built into Python)

**Layout:** `gui.py` defines `MinecraftLauncherGUI` (imported by `minecraft.py`
as `from gui import MinecraftLauncherGUI`). It only holds `__init__` (window
setup and shared state) and `run()`. Every feature lives in a mixin class under
`ui/`, and `MinecraftLauncherGUI` inherits all of them:

```python
class MinecraftLauncherGUI(
    ThemeMixin, LayoutMixin, ConsoleMixin, SettingsMixin, ContainerStateMixin,
    ContainerControlMixin, DoctorMixin, UpdatesMixin, ResourceMonitorMixin,
    ProfilesMixin, ProfileImportMixin, ProfileInfoMixin,
):
    ...
```

The mixins share one `self`, so any of them can use `self.window`,
`self.colors`, `self.log()`, `self._gather_config()` and the widgets created in
`_create_widgets` / the panel builders. Rules that keep this manageable:

- `ui/*` modules import from `core/`, `ui.common` and `ui.base` only, never
  from `gui` or from each other (no import cycles).
- Paths relative to the repo use `APP_DIR` from `ui.common`, not `__file__`
  (which would point at `ui/`).
- Method names are unique across mixins; nothing relies on MRO overriding.
- Worker threads never touch Tk: they hand results back with
  `self.window.after(0, ...)`.
- Every mixin inherits `ui.base.GUIBase`, which tells mypy what the shared
  `self` holds: bare annotations for each attribute the GUI sets, and stubs
  (under `TYPE_CHECKING`) for methods one mixin calls on another. A new shared
  attribute or cross-mixin call needs a line there. GUIBase is empty at
  runtime and sits last in the MRO, so it never shadows a real method
  (`tests/test_gui_base.py` checks this).

**Components:**
- **Detection Frame:** Dropdowns for runtime/GPU/display/audio
- **Control Frame:** Start/Stop/Restart/Doctor/Save buttons
- **Status Label:** Current state (Ready/Starting/Running/Stopped)
- **Log Output:** Scrollable text area with real-time logs

**Key Features:**
- Auto-populates dropdowns with detected values
- "auto" option uses detection, others override
- Threading for non-blocking container start
- Real-time log streaming via callbacks
- Button state management (disable start when running, etc.)
- Configuration persistence

**User Flow:**
1. Double-click `minecraft.py` → GUI opens
2. Shows detected configuration (all dropdowns set to "auto")
3. User optionally overrides settings
4. Click "Start" → Validation → Container starts
5. Logs stream to window
6. Click "Save Config" to persist overrides

---

### 3. CLI Interface (`cli.py`)

**Framework:** Rich (optional) + Questionary (optional)

**Commands:**
```bash
start      # Start container (with confirmation)
stop       # Stop container
restart    # Restart container
logs       # Show/follow logs
status     # Check if running
doctor     # Validate system
```

**Flags:**
```bash
--runtime docker     # Override runtime detection
--gpu amd            # Override GPU detection
--display wayland    # Override display detection
--audio none         # Override audio detection
--detached, -d       # Run in background
--yes, -y            # Skip confirmation
--no-gui             # Force CLI mode
```

**Key Features:**
- Rich tables for configuration display (with fallback)
- Interactive confirmation menus (with fallback)
- Colored status indicators (✓ ✗ ⚠)
- Validation with helpful error messages
- Graceful degradation without optional deps

**User Flow:**
1. Run `./minecraft.py start`
2. System detection → Display table
3. Confirmation prompt (unless --yes)
4. Validation checks
5. X11 permissions (if needed)
6. Container starts, logs stream
7. Returns on completion

---

### 4. Core Backend (`core/`)

Shared business logic used by both interfaces.

#### `detector.py` - System Auto-Detection

**Functions:**
- `detect_system()` → Full detection dict
- `detect_runtime()` → podman or docker
- `detect_gpu()` → nvidia or amd
- `detect_display()` → x11 or wayland
- `detect_audio()` → pulseaudio or none
- `get_detection_details()` → Detailed info for display

**Detection Methods:**
- Runtime: `which podman || which docker`
- GPU: Check `/dev/nvidia*` vs `/dev/dri`, fallback to `lspci`
- Display: `$XDG_SESSION_TYPE` env var
- Audio: Check `/run/user/UID/pulse/native` socket, try `pactl info`

#### `config.py` - Configuration Management

**Location:** `~/.config/minecraft-launcher/config.yaml`

**Format:**
```yaml
runtime: ""       # Empty = auto-detect
gpu: ""
display: ""
audio: ""
auto_xhost: true  # Auto-run xhost for X11
```

**Functions:**
- `load_config()` → Load from file or empty dict
- `save_config()` → Write to file
- `merge_config()` → Saved overrides detection
- `reset_config()` → Delete config file

**Merge Logic:**
```python
# Detected: {runtime: 'podman', gpu: 'nvidia'}
# Saved:    {runtime: '', gpu: 'amd'}
# Result:   {runtime: 'podman', gpu: 'amd'}
#           (empty saved = use detected, non-empty = override)
```

#### `composer.py` - Compose Command Builder

**Purpose:** Build correct compose file order.

**Example Output:**
```bash
podman compose \
  -f compose.base.yaml \
  -f compose.podman.yaml \
  -f compose.nvidia.yaml \
  -f compose.x11.yaml \
  -f compose.audio-pulseaudio.yaml \
  up
```

**Functions:**
- `build_compose_command()` → Full command list
- `get_compose_files()` → List of files to use
- `validate_compose_files_exist()` → Check files present
- `get_command_preview()` → Human-readable string

#### `validator.py` - Pre-flight Validation

**Checks:**
- Runtime installed and working
- GPU devices exist (/dev/nvidia*, /dev/dri)
- Display server available (DISPLAY or WAYLAND_DISPLAY)
- Audio system running (optional)
- Compose files present
- X11 permissions (for X11)

**Output:**
```python
ValidationIssue(
    message="NVIDIA GPU selected but /dev/nvidia0 not found",
    level='error',  # or 'warning'
    fix_hint="Install NVIDIA drivers or select 'amd' GPU type"
)
```

**Error vs Warning:**
- Error (✗): Blocks startup
- Warning (⚠): Allows startup but shows issue

#### `container.py` - Container Lifecycle

**Class:** `ContainerManager`

**Methods:**
```python
.start(detached=False, output_callback=None)
.stop()
.restart(output_callback=None)
.logs(follow=False, tail=None) → Iterator[str]
.status() → dict
.is_running() → bool
```

**Threading Support:**
- `start_container_async()` → For GUI non-blocking start
- Uses callbacks for output streaming
- Thread-safe status updates

---

## Data Flow

### Starting Container (GUI)

```
User clicks "Start"
    ↓
GUI: _gather_config() → {runtime, gpu, display, audio}
    ↓
GUI: validate_system(config) → (valid, issues)
    ↓
GUI: Display issues, abort if errors
    ↓
GUI: run_xhost_if_needed() → Set X11 permissions
    ↓
GUI: start_container_async() → Start in background thread
    ↓
Container: build_compose_command() → ['podman', 'compose', '-f', ...]
    ↓
Container: subprocess.Popen() → Execute command
    ↓
Container: Stream output via callback
    ↓
GUI: log() → Append to text widget
    ↓
Container: completion_callback(success)
    ↓
GUI: Update button states, status label
```

### Starting Container (CLI)

```
User runs: ./minecraft.py start
    ↓
CLI: Detect system, load config, merge
    ↓
CLI: Show configuration table (rich or plain)
    ↓
CLI: Confirm with user (unless --yes)
    ↓
CLI: Validate system
    ↓
CLI: Display validation issues
    ↓
CLI: run_xhost_if_needed()
    ↓
CLI: ContainerManager.start(output_callback=print)
    ↓
Container: Stream logs to terminal
    ↓
CLI: Exit with status code
```

---

## Configuration Precedence

**Priority (highest to lowest):**

1. **Command-line flags** (CLI only)
   ```bash
   ./minecraft.py start --runtime docker --gpu amd
   ```

2. **Saved configuration** (`~/.config/minecraft-launcher/config.yaml`)
   ```yaml
   runtime: ""      # Empty = skip
   gpu: "amd"       # Override detection
   ```

3. **Auto-detection** (fallback)
   ```python
   detect_system() → {runtime: 'podman', gpu: 'nvidia', ...}
   ```

**Example Merge:**
```python
# Command line:  --runtime docker
# Saved config:  gpu: "amd", display: ""
# Detection:     runtime: "podman", gpu: "nvidia", display: "x11"

# Final result:
{
    'runtime': 'docker',    # From CLI flag
    'gpu': 'amd',           # From saved config
    'display': 'x11'        # From detection (saved was empty)
}
```

---

## Error Handling

### Graceful Fallbacks

**Missing Optional Dependencies:**
```python
try:
    from rich.console import Console
    RICH_AVAILABLE = True
except ImportError:
    RICH_AVAILABLE = False
    # Use plain print() instead
```

**Missing Tkinter:**
```python
if should_use_gui():
    try:
        from gui import MinecraftLauncherGUI
        app.run()
    except ImportError:
        launch_cli()  # Fallback to CLI
```

**Validation Failures:**
- Display all issues (errors + warnings)
- Block startup only on errors
- Provide fix hints for each issue

---

## Extension Points

### Adding New Detection

**Example: Detect podman-desktop vs podman-cli**

```python
# In detector.py
def detect_runtime_variant():
    if shutil.which('podman-desktop'):
        return 'podman-desktop'
    return 'podman'
```

### Adding New Command (CLI)

**Example: Add "backup" command**

```python
# In cli.py
def run_backup(args):
    console = Console() if RICH_AVAILABLE else None
    _print(console, "Creating backup...")
    # Backup logic here

# In minecraft.py
parser.add_argument('command', choices=[..., 'backup'])
```

### Adding GUI Feature

**Example: Add "Backup" button**

Put the feature in its own mixin, add the button where it belongs, and add the
mixin to `MinecraftLauncherGUI`'s bases:

```python
# ui/backup.py
class BackupMixin:
    def backup_data(self):
        self.log("Creating backup...")
        # Backup logic here (run slow work in a thread, report via self.window.after)

# ui/layout.py, in _create_widgets
self.btn_backup = ttk.Button(control_frame, text="Backup",
                             command=self.backup_data)

# gui.py
from ui.backup import BackupMixin

class MinecraftLauncherGUI(..., BackupMixin):
```

If it extends an existing area (say, another profile action), add the method to
that area's mixin instead, e.g. `ui/profiles.py`.

---

## Testing Scenarios

### CLI Testing

```bash
# Auto-detection
./minecraft.py --no-gui start

# Override detection
./minecraft.py --no-gui start --runtime docker --gpu amd

# Non-interactive
./minecraft.py --no-gui start --yes --detached

# Validation
./minecraft.py --no-gui doctor

# Status check
./minecraft.py --no-gui status
```

### GUI Testing

1. **Double-click launch:** Window opens, detection populates dropdowns
2. **Override settings:** Change GPU to "amd", verify compose command updates
3. **Save config:** Click "Save Config", restart GUI, verify persists
4. **Doctor check:** Click "Doctor", verify validation runs
5. **Start/Stop:** Click "Start", verify logs stream, click "Stop"

### Edge Cases

- No runtime installed → Error with install hint
- Wrong GPU selected → Error with device check
- No display (SSH) → Falls back to CLI
- Compose files missing → Error with file paths
- Container already running → Status check works

---

## Performance Considerations

**Lazy Loading:**
- GUI code not loaded in CLI mode
- CLI code not loaded in GUI mode
- ~50ms faster startup per interface

**Threading:**
- Container start runs in background (GUI)
- Main thread remains responsive
- Log streaming via callbacks

**Caching:**
- Detection runs once per launch
- Config file read once
- Status checks are quick (ps command)

---

## Security Considerations

**Configuration File:**
- Stored in user home: `~/.config/minecraft-launcher/`
- Contains no secrets (only preferences)
- YAML format prevents code injection

**Command Building:**
- Uses list arguments (not shell strings)
- No user input in shell commands
- Subprocess doesn't use `shell=True`

**X11 Permissions:**
- Only grants access to local user
- `xhost +SI:localuser:$USER`
- Doesn't disable access control globally

---

## Dependencies

### Required

- **Python 3.7+** (standard library)
- **PyYAML** (config parsing)

### Optional (CLI Enhancement)

- **rich** (beautiful terminal output)
- **questionary** (interactive menus)

### Built-in (No Install)

- **tkinter** (GUI)
- **subprocess** (command execution)
- **threading** (background tasks)
- **pathlib** (file operations)

---

## Related Documentation

- [TLAUNCHER-STRUCTURE.md](TLAUNCHER-STRUCTURE.md) - Minecraft/TLauncher file organization
- [README.md](README.md) - User-facing quick start guide
- [manual-runbook.md](manual-runbook.md) - Manual compose commands

---

## Quick Reference

| What | File | Lines |
|------|------|-------|
| Entry point | minecraft.py | ~200 |
| GUI entry | gui.py | ~110 |
| GUI features | ui/*.py | ~2,600 |
| CLI interface | cli.py | ~780 |
| System detection | core/detector.py | ~470 |
| Config management | core/config.py | ~190 |
| Command builder | core/composer.py | ~190 |
| Validation | core/validator.py | ~370 |
| Container ops | core/container.py | ~340 |
| Profile/modpack import & export | core/packs.py | ~700 |

---

**Architecture Pattern:** MVC + Strategy Pattern
- **Model:** core/* (business logic)
- **View:** gui.py + ui/ + cli.py (presentation)
- **Controller:** minecraft.py (dispatch)
- **Strategy:** Interface selection based on environment

---

**Design Principles:**
✅ Separation of concerns
✅ DRY (Don't Repeat Yourself)
✅ Graceful degradation
✅ Fail-fast validation
✅ Clear error messages
✅ Progressive enhancement
