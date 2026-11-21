import pytest

from core import validator
from core.validator import COMPOSE_V2_MISSING


@pytest.fixture
def detection(monkeypatch):
    state = {"provider": "", "legacy": False}
    monkeypatch.delenv("PODMAN_COMPOSE_PROVIDER", raising=False)
    monkeypatch.setattr(validator, "detect_compose_provider", lambda _r: state["provider"])
    monkeypatch.setattr(validator, "has_legacy_podman_compose", lambda: state["legacy"])
    return state


def check(runtime="podman"):
    return validator._check_compose_provider({"runtime": runtime})


def test_docker_needs_no_provider(detection):
    assert check("docker") == []


def test_provider_found(detection):
    detection["provider"] = "/usr/bin/docker-compose"
    assert check() == []


def test_env_override_skips_detection(detection, monkeypatch):
    monkeypatch.setenv("PODMAN_COMPOSE_PROVIDER", "/my/compose")
    monkeypatch.setattr(
        validator, "detect_compose_provider", lambda _r: pytest.fail("should not detect")
    )
    assert check() == []


def test_legacy_only_is_a_warning(detection):
    detection["legacy"] = True
    (issue,) = check()
    assert issue.code == COMPOSE_V2_MISSING
    assert issue.level == "warning"
    assert not issue.is_blocking()
    assert "install-compose" in issue.fix_hint


def test_nothing_installed_is_an_error(detection):
    (issue,) = check()
    assert issue.code == COMPOSE_V2_MISSING
    assert issue.level == "error"
    assert issue.is_blocking()


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
