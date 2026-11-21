import itertools
import os
from pathlib import Path

import pytest

from core import composer

REPO = Path(__file__).resolve().parent.parent


def cfg(**kw):
    base = {"runtime": "podman", "gpu": "nvidia", "display": "x11", "audio": "pulseaudio"}
    base.update(kw)
    return base


# ── get_compose_files ────────────────────────────────────────────────────────


def test_compose_files_standard_order():
    assert composer.get_compose_files(cfg()) == [
        "compose.base.yaml",
        "compose.podman.yaml",
        "compose.nvidia.yaml",
        "compose.x11.yaml",
        "compose.audio-pulseaudio.yaml",
    ]


def test_compose_files_docker_wayland_amd_no_audio():
    files = composer.get_compose_files(
        cfg(runtime="docker", gpu="amd", display="wayland", audio="none")
    )
    assert files == [
        "compose.base.yaml",
        "compose.docker.yaml",
        "compose.amd.yaml",
        "compose.wayland.yaml",
        "compose.audio-none.yaml",
    ]


@pytest.mark.parametrize("runtime", ["podman", "docker"])
def test_compose_files_wslg_ignores_gpu_and_audio(runtime):
    files = composer.get_compose_files(
        cfg(runtime=runtime, gpu="intel", display="wslg", audio="pulseaudio")
    )
    assert files == ["compose.base.yaml", f"compose.{runtime}.yaml", "compose.wslg.yaml"]


@pytest.mark.parametrize(
    ("runtime", "gpu", "display", "audio"),
    list(
        itertools.product(
            ["podman", "docker"],
            ["nvidia", "amd", "intel"],
            ["x11", "wayland", "wslg"],
            ["pulseaudio", "none"],
        )
    ),
)
def test_every_supported_combo_has_its_files(runtime, gpu, display, audio):
    conf = cfg(runtime=runtime, gpu=gpu, display=display, audio=audio)
    ok, missing = composer.validate_compose_files_exist(conf)
    assert ok, missing


def test_missing_compose_file_reported():
    ok, missing = composer.validate_compose_files_exist(cfg(gpu="voodoo"))
    assert not ok
    assert missing == ["compose.voodoo.yaml"]


# ── build_compose_command ────────────────────────────────────────────────────


def test_build_compose_command_ordering():
    conf = cfg(runtime="docker", gpu="intel", display="wayland", audio="none")
    cmd = composer.build_compose_command(conf, "up", ["-d", "--force-recreate"])
    assert cmd[:2] == ["docker", "compose"]
    files = composer.get_compose_files(conf)
    flags = cmd[2 : 2 + 2 * len(files)]
    assert flags[0::2] == ["-f"] * len(files)
    assert flags[1::2] == [str(REPO / f) for f in files]
    assert cmd[2 + 2 * len(files) :] == ["up", "-d", "--force-recreate"]


def test_build_compose_command_without_extra_args_ends_with_action():
    cmd = composer.build_compose_command(cfg(), "down")
    assert cmd[-1] == "down"
    assert cmd.count("-f") == 5


def test_command_preview():
    preview = composer.get_command_preview(cfg(display="wslg"), "logs")
    assert preview.startswith("podman compose -f ")
    assert preview.endswith("compose.wslg.yaml logs")


def test_compose_directory_is_repo_root():
    assert composer.get_compose_directory().resolve() == REPO


# ── build_compose_env ────────────────────────────────────────────────────────

_ENV_VARS = (
    "TLAUNCHER_JAVA",
    "TLAUNCHER_MEM_LIMIT",
    "CONTAINERS_CONF_OVERRIDE",
    "NO_COLOR",
    "COMPOSE_ANSI",
    "COMPOSE_PROGRESS",
    "PODMAN_COMPOSE_PROVIDER",
    "XAUTHORITY",
)


@pytest.fixture
def clean_env(monkeypatch):
    for var in _ENV_VARS:
        monkeypatch.delenv(var, raising=False)
    calls = []

    def fake_provider(runtime):
        calls.append(runtime)
        return "/fake/bin/docker-compose"

    monkeypatch.setattr(composer, "detect_compose_provider", fake_provider)
    return calls


def test_env_podman_defaults(clean_env):
    env = composer.build_compose_env(cfg(java="25", memory="12"))
    assert env["TLAUNCHER_JAVA"] == "25"
    assert env["TLAUNCHER_MEM_LIMIT"] == "12g"
    assert env["NO_COLOR"] == "1"
    assert env["COMPOSE_ANSI"] == "never"
    assert env["COMPOSE_PROGRESS"] == "plain"
    conf_override = Path(env["CONTAINERS_CONF_OVERRIDE"])
    assert conf_override.name == "containers-quiet.conf"
    assert conf_override.is_file()
    assert env["PODMAN_COMPOSE_PROVIDER"] == "/fake/bin/docker-compose"
    assert clean_env == ["podman"]


def test_env_java_and_memory_fall_back_to_defaults(clean_env):
    env = composer.build_compose_env(cfg(java="8", memory="999g"))
    assert env["TLAUNCHER_JAVA"] == "21"
    assert env["TLAUNCHER_MEM_LIMIT"] == "8g"


def test_env_docker_has_no_podman_bits(clean_env):
    env = composer.build_compose_env(cfg(runtime="docker"))
    assert "CONTAINERS_CONF_OVERRIDE" not in env
    assert "PODMAN_COMPOSE_PROVIDER" not in env
    assert env["NO_COLOR"] == "1"
    assert clean_env == []


def test_env_respects_preset_values(clean_env, monkeypatch):
    monkeypatch.setenv("NO_COLOR", "0")
    monkeypatch.setenv("COMPOSE_PROGRESS", "tty")
    monkeypatch.setenv("CONTAINERS_CONF_OVERRIDE", "/my/containers.conf")
    monkeypatch.setenv("PODMAN_COMPOSE_PROVIDER", "/my/compose")
    env = composer.build_compose_env(cfg())
    assert env["NO_COLOR"] == "0"
    assert env["COMPOSE_PROGRESS"] == "tty"
    assert env["CONTAINERS_CONF_OVERRIDE"] == "/my/containers.conf"
    assert env["PODMAN_COMPOSE_PROVIDER"] == "/my/compose"
    assert clean_env == []  # no detection when the user already picked a provider


def test_env_java_comes_from_config_not_environment(clean_env, monkeypatch):
    monkeypatch.setenv("TLAUNCHER_JAVA", "25")
    env = composer.build_compose_env(cfg(java="21"))
    assert env["TLAUNCHER_JAVA"] == "21"


def test_env_no_provider_found(clean_env, monkeypatch):
    monkeypatch.setattr(composer, "detect_compose_provider", lambda _r: "")
    env = composer.build_compose_env(cfg())
    assert "PODMAN_COMPOSE_PROVIDER" not in env


def test_env_does_not_touch_os_environ(clean_env):
    before = dict(os.environ)
    composer.build_compose_env(cfg())
    assert dict(os.environ) == before


def test_xauthority_unset_without_home_cookie_uses_dev_null(clean_env):
    env = composer.build_compose_env(cfg(display="x11"))
    assert env["XAUTHORITY"] == "/dev/null"


def test_xauthority_unset_uses_home_cookie(clean_env, fake_home):
    cookie = fake_home / ".Xauthority"
    cookie.write_bytes(b"cookie")
    env = composer.build_compose_env(cfg(display="x11"))
    assert env["XAUTHORITY"] == str(cookie)


def test_xauthority_existing_file_kept(clean_env, monkeypatch, tmp_path):
    cookie = tmp_path / "xauth-abc"
    cookie.write_bytes(b"cookie")
    monkeypatch.setenv("XAUTHORITY", str(cookie))
    env = composer.build_compose_env(cfg(display="x11"))
    assert env["XAUTHORITY"] == str(cookie)


def test_xauthority_stale_path_replaced(clean_env, monkeypatch, tmp_path):
    monkeypatch.setenv("XAUTHORITY", str(tmp_path / "gone"))
    env = composer.build_compose_env(cfg(display="x11"))
    assert env["XAUTHORITY"] == "/dev/null"


@pytest.mark.parametrize("display", ["wayland", "wslg"])
def test_xauthority_only_resolved_for_x11(clean_env, display):
    env = composer.build_compose_env(cfg(display=display))
    assert "XAUTHORITY" not in env


# ── strip_ansi ───────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("raw", "clean"),
    [
        ("plain text", "plain text"),
        ("\x1b[4mtlauncher\x1b[0m started", "tlauncher started"),
        ("\x1b[1;32m✓\x1b[0m Container up", "✓ Container up"),
        ("\x1b[2K\x1b[1Gpulling", "pulling"),
        ("\x1b[?25lhidden cursor\x1b[?25h", "hidden cursor"),
        ("\x1b]0;window title\x07after", "after"),
        ("", ""),
    ],
)
def test_strip_ansi(raw, clean):
    assert composer.strip_ansi(raw) == clean
