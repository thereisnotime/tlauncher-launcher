import pytest

from core import validator
from core.validator import COMPOSE_V2_MISSING, PODMAN_SOCKET_DOWN


@pytest.fixture
def detection(monkeypatch):
    state = {"provider": "", "legacy": False, "socket": False}
    monkeypatch.delenv("PODMAN_COMPOSE_PROVIDER", raising=False)
    monkeypatch.setattr(validator, "detect_compose_provider", lambda _r: state["provider"])
    monkeypatch.setattr(validator, "has_legacy_podman_compose", lambda: state["legacy"])
    monkeypatch.setattr(validator, "podman_socket_ready", lambda: state["socket"])
    return state


def check(runtime="podman"):
    return validator._check_compose_provider({"runtime": runtime})


def test_docker_needs_no_provider(detection):
    assert check("docker") == []


def test_podman_compose_is_fine_on_its_own(detection):
    detection["legacy"] = True
    assert check() == []


def test_docker_compose_with_socket_is_fine(detection):
    detection["provider"] = "/usr/bin/docker-compose"
    detection["socket"] = True
    assert check() == []


def test_docker_compose_without_socket_is_an_error(detection):
    detection["provider"] = "/home/u/.local/bin/docker-compose"
    (issue,) = check()
    assert issue.code == PODMAN_SOCKET_DOWN
    assert issue.is_blocking()
    assert "podman.socket" in issue.fix_hint
    assert "podman-compose" in issue.fix_hint


def test_podman_compose_wins_even_without_socket(detection):
    detection["legacy"] = True
    detection["provider"] = "/home/u/.local/bin/docker-compose"
    assert check() == []


def test_env_override_skips_detection(detection, monkeypatch):
    monkeypatch.setenv("PODMAN_COMPOSE_PROVIDER", "/my/compose")
    monkeypatch.setattr(
        validator, "detect_compose_provider", lambda _r: pytest.fail("should not detect")
    )
    assert check() == []


def test_nothing_installed_is_an_error(detection):
    (issue,) = check()
    assert issue.code == COMPOSE_V2_MISSING
    assert issue.level == "error"
    assert issue.is_blocking()
    assert "podman-compose" in issue.fix_hint


def test_missing_compose_file_is_blocking():
    conf = {"runtime": "podman", "gpu": "voodoo", "display": "x11", "audio": "none"}
    (issue,) = validator._check_compose_files(conf)
    assert issue.is_blocking()
    assert "compose.voodoo.yaml" in issue.message


def test_wslg_skips_gpu_and_audio_checks():
    conf = {"runtime": "podman", "gpu": "nvidia", "display": "wslg", "audio": "pulseaudio"}
    assert validator._check_gpu(conf) == []
    assert validator._check_audio(conf) == []


def test_xhost_skipped_when_disabled():
    conf = {"runtime": "podman", "display": "x11", "auto_xhost": False}
    assert validator._check_xhost(conf) == []
    assert validator.run_xhost_if_needed(conf) is True
