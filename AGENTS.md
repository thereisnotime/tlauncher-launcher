# AGENTS.md

Guidance for anyone, human or AI agent, changing this repo. Read README.md for what the
project does and WRAPPER-STRUCTURE.md for the code layout; this file is the short list of
conventions and traps that aren't obvious from the code.

## What this is

A Python launcher (Tk GUI + CLI, `minecraft.py`) that runs TLauncher/Minecraft inside a
rootless podman (or docker) container built from layered compose files. It also imports
and updates modpacks (`.mrpack`) into TLauncher's folder layout.

## Commands

```bash
just install-dev     # .venv with ruff, pytest, mypy
just test            # py_compile (incl. ui/) + pytest, ~1s, offline
just lint            # ruff check;  just format / just format-check
just ci              # format-check + lint + test, same as CI
./minecraft.py --version
./minecraft.py --no-gui doctor
```

CI (`.github/workflows/`) runs lint, format-check, `just test`, mypy (non-blocking) and
builds the image with Java 21 and 25 under docker and podman.

## Rules

- **Podman first.** Rootless podman is the target. Use podman for any local container
  work; docker is supported by the code, not by our tooling. Name throwaway containers
  `tl-*` and remove them (and their volumes/images) when done.
- **Compose provider:** `core/detector.choose_compose_provider()` prefers `podman-compose`
  and only uses a `docker-compose` binary when podman's API socket is reachable, and it is
  always set explicitly via `PODMAN_COMPOSE_PROVIDER`. Don't change this to "docker-compose
  if present": podman picks it first on its own, and without `podman.socket` every start
  fails (this happened). `PYTHONUNBUFFERED=1` keeps podman-compose's output live.
- **Archives are untrusted.** Anything read from a zip/.mrpack/URL goes through
  `core/packs.safe_join()` / `_safe_name()`. Never build a path from archive data or
  metadata directly. Downloads verify size and hashes; HTML responses are refused.
- **TLauncher layout:** a profile with its own `gameDir` runs with
  `--gameDir /home/app/.minecraft/versions/<id>` (verified from real logs). Modpacks live
  there with a `.mrpack-files.json` manifest. TLauncher rewrites
  `tlauncher-data/tlauncher-2.0.properties` on exit, so only edit it (e.g. game RAM) while
  the `tlauncher` container isn't running.
- **Game RAM vs container cap:** Minecraft's heap (`minecraft.memory.ram3`) must stay
  ~1.5 GB below `TLAUNCHER_MEM_LIMIT` (`core/game_ram.py`), or the game is OOM-killed.
- **Images are tagged per Java version** (`tlauncher-java:21|25`); compose picks the tag
  from `TLAUNCHER_JAVA`. Build with `core/container.build_image_command()`, not ad hoc.
- **Loader installs** (NeoForge/Forge) run the official installer inside the launcher
  image with `--install-client`; files must end up owned by the user (`--userns=keep-id`).

## GUI conventions

- `gui.py` holds `MinecraftLauncherGUI`, built from mixins in `ui/` (one feature area per
  file). Mixins import only from `core` and `ui.common`/`ui.base`, never from each other.
- `ui/base.GUIBase` declares every shared `self.X` attribute and every method one mixin
  calls on another (stubs under `TYPE_CHECKING`). When you add either, add it there or
  mypy will flag it. `tests/test_gui_base.py` checks stubs never shadow real methods.
- Tk is not thread-safe: background work runs in threads and touches widgets only via
  `self.window.after(0, ...)`.
- Use `APP_DIR` from `ui.common`, not `Path(__file__)`, for repo-relative paths.

## Tests

- Offline and fast. Network goes through the local `http_server` fixture
  (`tests/conftest.py`); `HOME` is a tmp dir, so nothing touches the real `~`.
- Loader installers must never run in tests; pre-create `versions/<id>/<id>.json` so
  `ensure_loader()` short-circuits (see `loader_home` / `no_network_loader`).
- New behaviour in `core/` gets tests; security-relevant code in `packs.py` gets a
  malicious-input test as well.

## Style and process

- Python 3.10+ (`requires-python`; CI tests 3.10 and 3.14); keep `ruff check` and `ruff format` clean (line length 100).
- Commit messages: `feat:`, `fix:`, `refactor:`, `docs:`, `test:`, `ci:`, `chore:` plus a
  short human summary; the body explains why. No AI boilerplate, no Co-Authored-By.
- Bump `version` in `pyproject.toml` for user-visible releases; the title bar shows it
  with the git commit (`core/version.py`).
- When behaviour changes, update README.md (user-facing), WRAPPER-STRUCTURE.md (layout),
  TLAUNCHER-STRUCTURE.md (data layout) and RUNBOOK-MANUAL.md (manual compose) as needed.
