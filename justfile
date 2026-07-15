# Minecraft Launcher - task runner (https://github.com/casey/just)

# The recipes are POSIX/bash based. On Windows run them inside WSL2 (recommended)
# or Git Bash; this points just at bash instead of the default `sh`, which is not
# present on a bare Windows install (causing "sh: not found").
set windows-shell := ['bash', '-cu']

# ── Configuration ───────────────────────────────────────────────────────────
venv        := '.venv'
python      := 'python3'
venv_python := venv / 'bin' / 'python'
venv_pip    := venv / 'bin' / 'pip'
ruff        := venv / 'bin' / 'ruff'

# ── Colors (printf interprets these escapes under any shell) ─────────────────
CYAN   := '\033[0;36m'
GREEN  := '\033[0;32m'
YELLOW := '\033[0;33m'
NC     := '\033[0m'

# Show available recipes, grouped by category
[private]
default:
    @just --list --unsorted --list-prefix '  '

# ── Play (just want to run Minecraft) ────────────────────────────────────────

# Build the container image (prefers Podman, falls back to Docker; override: just build docker)
[group('Play')]
build engine='auto':
    #!/usr/bin/env bash
    set -euo pipefail
    engine="{{engine}}"
    if [ "$engine" = auto ]; then
        if command -v podman >/dev/null 2>&1; then engine=podman
        elif command -v docker >/dev/null 2>&1; then engine=docker
        else
            printf "{{YELLOW}}Neither podman nor docker found. Install one to build.{{NC}}\n" >&2
            exit 1
        fi
    elif ! command -v "$engine" >/dev/null 2>&1; then
        printf "{{YELLOW}}'$engine' not found.{{NC}}\n" >&2
        exit 1
    fi
    printf "{{CYAN}}Building container image with $engine...{{NC}}\n"
    "$engine" build -f Containerfile -t tlauncher-java .
    printf "{{GREEN}}✓ Build completed with $engine{{NC}}\n"

# Install runtime dependencies into .venv
[group('Play')]
install: venv
    @printf "{{CYAN}}Installing runtime dependencies...{{NC}}\n"
    {{venv_pip}} install -r requirements.txt
    @printf "{{GREEN}}✓ Runtime dependencies installed in {{venv}}{{NC}}\n"

# Launch the Minecraft launcher (GUI)
[group('Play')]
run:
    @printf "{{CYAN}}Starting Minecraft launcher...{{NC}}\n"
    @if [ -x "{{venv_python}}" ]; then {{venv_python}} minecraft.py; else ./minecraft.py; fi

# Install a desktop/menu shortcut (Linux .desktop, or Windows via PowerShell)
[group('Play')]
shortcut:
    #!/usr/bin/env bash
    set -euo pipefail
    case "$(uname -s)" in
        Linux|Darwin)
            printf "{{CYAN}}Installing desktop shortcut...{{NC}}\n"
            ./create-shortcut.sh
            ;;
        MINGW*|MSYS*|CYGWIN*|Windows_NT)
            printf "{{CYAN}}Creating Windows shortcut...{{NC}}\n"
            powershell.exe -ExecutionPolicy Bypass -File create-shortcut.ps1
            ;;
        *)
            printf "{{YELLOW}}Unsupported platform: $(uname -s). Run create-shortcut.sh or create-shortcut.ps1 manually.{{NC}}\n" >&2
            exit 1
            ;;
    esac

# Run system diagnostics
[group('Play')]
doctor:
    @printf "{{CYAN}}Running system diagnostics...{{NC}}\n"
    @if [ -x "{{venv_python}}" ]; then {{venv_python}} minecraft.py doctor; else ./minecraft.py doctor; fi

# ── Develop (want to work on the code) ───────────────────────────────────────

# Create a virtual environment in .venv
[group('Develop')]
venv:
    #!/usr/bin/env bash
    set -euo pipefail
    if [ ! -d "{{venv}}" ]; then
        printf "{{CYAN}}Creating virtual environment in {{venv}}...{{NC}}\n"
        {{python}} -m venv {{venv}}
        {{venv_pip}} install --upgrade pip
        printf "{{GREEN}}✓ Virtual environment created{{NC}}\n"
    else
        printf "{{YELLOW}}Virtual environment {{venv}} already exists{{NC}}\n"
    fi

# Install development dependencies into .venv (includes ruff)
[group('Develop')]
install-dev: venv
    @printf "{{CYAN}}Installing development dependencies...{{NC}}\n"
    {{venv_pip}} install -r requirements-dev.txt
    @printf "{{GREEN}}✓ Development dependencies installed in {{venv}}{{NC}}\n"

# Run ruff linter on Python code
[group('Develop')]
lint:
    @printf "{{CYAN}}Running ruff linter...{{NC}}\n"
    {{ruff}} check .

# Run ruff linter and auto-fix issues
[group('Develop')]
lint-fix:
    @printf "{{CYAN}}Running ruff linter with auto-fix...{{NC}}\n"
    {{ruff}} check --fix .

# Format Python code with ruff
[group('Develop')]
format:
    @printf "{{CYAN}}Formatting Python code with ruff...{{NC}}\n"
    {{ruff}} format .

# Check Python code formatting without modifying files
[group('Develop')]
format-check:
    @printf "{{CYAN}}Checking Python code formatting...{{NC}}\n"
    {{ruff}} format --check .

# Run Python syntax checks and basic validation
[group('Develop')]
test:
    #!/usr/bin/env bash
    set -euo pipefail
    printf "{{CYAN}}Running Python syntax checks...{{NC}}\n"
    PY="{{python}}"; [ -x "{{venv_python}}" ] && PY="{{venv_python}}"
    "$PY" -m py_compile minecraft.py gui.py cli.py core/*.py
    printf "{{GREEN}}✓ Python syntax validation passed{{NC}}\n"

# Validate Docker Compose files
[group('Develop')]
validate-compose:
    @printf "{{CYAN}}Validating Docker Compose files...{{NC}}\n"
    @DISPLAY=:0 XAUTHORITY=/tmp/.Xauthority USER=testuser docker compose -f compose.base.yaml config > /dev/null
    @printf "{{GREEN}}✓ Compose files validated{{NC}}\n"

# Run all CI checks (format, lint, test)
[group('Develop')]
ci: format-check lint test
    @printf "{{GREEN}}✓ All CI checks passed{{NC}}\n"

# Run full development workflow
[group('Develop')]
all: clean install-dev ci build
    @printf "{{GREEN}}✓ Full workflow completed{{NC}}\n"

# ── Maintenance ──────────────────────────────────────────────────────────────

# Clean up Python cache and temporary files
[group('Maintenance')]
clean:
    @printf "{{CYAN}}Cleaning up...{{NC}}\n"
    -find . -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null
    -find . -type f -name "*.pyc" -delete
    -find . -type f -name "*.pyo" -delete
    -find . -type f -name "*.egg-info" -exec rm -rf {} + 2>/dev/null
    -find . -type d -name ".ruff_cache" -exec rm -rf {} + 2>/dev/null
    @printf "{{GREEN}}✓ Cleanup completed{{NC}}\n"

# Remove the virtual environment
[group('Maintenance')]
clean-venv:
    @printf "{{CYAN}}Removing virtual environment...{{NC}}\n"
    rm -rf {{venv}}
    @printf "{{GREEN}}✓ Virtual environment removed{{NC}}\n"
