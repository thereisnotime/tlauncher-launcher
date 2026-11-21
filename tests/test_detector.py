import subprocess

import pytest

from core import detector


def fake_run(stdout="", exc=None):
    def run(cmd, **_kw):
        if exc:
            raise exc
        return subprocess.CompletedProcess(cmd, 0, stdout=stdout, stderr="")

    return run


@pytest.mark.parametrize(
    ("output", "expected"),
    [
        ("2.29.1\n", True),
        ("v2.20.3", True),
        ("5.0.1", True),
        ("10.1.0", True),
        ("1.29.2", False),
        ("v1.27.4", False),
        ("", False),
        ("docker-compose version 1.29.2, build unknown", False),
        ("garbage", False),
    ],
)
def test_is_compose_v2_parses_version(monkeypatch, output, expected):
    monkeypatch.setattr(detector.subprocess, "run", fake_run(output))
    assert detector._is_compose_v2("/x/docker-compose") is expected


@pytest.mark.parametrize(
    "exc",
    [FileNotFoundError(), PermissionError(), subprocess.TimeoutExpired("docker-compose", 3)],
)
def test_is_compose_v2_handles_failures(monkeypatch, exc):
    monkeypatch.setattr(detector.subprocess, "run", fake_run(exc=exc))
    assert detector._is_compose_v2("/x/docker-compose") is False


def _exe(path, text="#!/bin/sh\n"):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)
    path.chmod(0o755)
    return path


@pytest.fixture
def provider_env(monkeypatch, tmp_path):
    """No docker-compose on PATH, no plugin dirs, empty ~/.local/bin."""
    monkeypatch.setattr(detector.shutil, "which", lambda _name: None)
    plugin_dir = tmp_path / "plugins"
    monkeypatch.setattr(
        detector,
        "_DOCKER_COMPOSE_PLUGIN_PATHS",
        (str(plugin_dir / "a" / "docker-compose"), str(plugin_dir / "b" / "docker-compose")),
    )
    v2 = set()
    monkeypatch.setattr(detector, "_is_compose_v2", lambda exe: exe in v2)
    return {"plugin_dir": plugin_dir, "v2": v2}


def test_provider_not_needed_for_docker(provider_env, monkeypatch):
    monkeypatch.setattr(detector.shutil, "which", lambda _n: "/usr/bin/docker-compose")
    provider_env["v2"].add("/usr/bin/docker-compose")
    assert detector.detect_compose_provider("docker") == ""


def test_provider_none_found(provider_env):
    assert detector.detect_compose_provider("podman") == ""


def test_provider_standalone_v2_on_path(provider_env, monkeypatch):
    monkeypatch.setattr(
        detector.shutil, "which", lambda n: "/opt/docker-compose" if n == "docker-compose" else None
    )
    provider_env["v2"].add("/opt/docker-compose")
    assert detector.detect_compose_provider("podman") == "/opt/docker-compose"


def test_provider_standalone_v1_skipped_for_local_bin(provider_env, monkeypatch, fake_home):
    monkeypatch.setattr(
        detector.shutil,
        "which",
        lambda n: "/usr/bin/docker-compose" if n == "docker-compose" else None,
    )
    local = _exe(fake_home / ".local" / "bin" / "docker-compose")
    provider_env["v2"].add(str(local))
    assert detector.detect_compose_provider("podman") == str(local)


def test_provider_local_bin_v1_rejected(provider_env, fake_home):
    _exe(fake_home / ".local" / "bin" / "docker-compose")  # not marked v2
    assert detector.detect_compose_provider("podman") == ""


def test_provider_local_bin_must_be_executable(provider_env, fake_home):
    local = _exe(fake_home / ".local" / "bin" / "docker-compose")
    local.chmod(0o644)
    provider_env["v2"].add(str(local))
    assert detector.detect_compose_provider("podman") == ""


def test_provider_falls_back_to_cli_plugin(provider_env):
    plugin = _exe(provider_env["plugin_dir"] / "b" / "docker-compose")
    assert detector.detect_compose_provider("podman") == str(plugin)


def test_provider_plugin_not_executable_ignored(provider_env):
    plugin = _exe(provider_env["plugin_dir"] / "a" / "docker-compose")
    plugin.chmod(0o644)
    assert detector.detect_compose_provider("podman") == ""


def test_has_legacy_podman_compose(monkeypatch):
    monkeypatch.setattr(detector.shutil, "which", lambda n: "/usr/bin/podman-compose")
    assert detector.has_legacy_podman_compose()
    monkeypatch.setattr(detector.shutil, "which", lambda n: None)
    assert not detector.has_legacy_podman_compose()


@pytest.mark.parametrize(
    ("available", "expected"),
    [({"podman", "docker"}, "podman"), ({"docker"}, "docker"), (set(), "podman")],
)
def test_detect_runtime(monkeypatch, available, expected):
    monkeypatch.setattr(detector.shutil, "which", lambda n: f"/bin/{n}" if n in available else None)
    assert detector.detect_runtime() == expected


@pytest.mark.parametrize(
    ("env", "expected"),
    [
        ({"XDG_SESSION_TYPE": "wayland"}, "wayland"),
        ({"XDG_SESSION_TYPE": "X11"}, "x11"),
        ({"XDG_SESSION_TYPE": "tty", "WAYLAND_DISPLAY": "wayland-0"}, "wayland"),
        ({"DISPLAY": ":0"}, "x11"),
        ({}, "x11"),
    ],
)
def test_detect_display(monkeypatch, env, expected):
    monkeypatch.setattr(detector, "is_wsl", lambda: False)
    for var in ("XDG_SESSION_TYPE", "WAYLAND_DISPLAY", "DISPLAY"):
        monkeypatch.delenv(var, raising=False)
    for k, v in env.items():
        monkeypatch.setenv(k, v)
    assert detector.detect_display() == expected


def test_detect_display_wsl_wins(monkeypatch):
    monkeypatch.setattr(detector, "is_wsl", lambda: True)
    monkeypatch.setenv("XDG_SESSION_TYPE", "wayland")
    assert detector.detect_display() == "wslg"


def test_is_wsl_from_env(monkeypatch):
    monkeypatch.setenv("WSL_DISTRO_NAME", "Ubuntu")
    assert detector.is_wsl()


@pytest.mark.parametrize(
    ("value", "expected"), [("eDP-1=1.5;HDMI-1=1;", 1.5), ("1;2;", 2.0), ("", 0.0), ("x=y", 0.0)]
)
def test_parse_qt_screen_factors(value, expected):
    assert detector._parse_qt_screen_factors(value) == expected
