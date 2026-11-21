import subprocess

import pytest

from core import container


@pytest.fixture(autouse=True)
def no_subprocess(monkeypatch):
    def boom(*_a, **_kw):
        raise AssertionError("subprocess must not be called")

    monkeypatch.setattr(subprocess, "run", boom)
    monkeypatch.setattr(subprocess, "Popen", boom)


@pytest.mark.parametrize(
    ("java", "tag"),
    [
        (None, "tlauncher-java:21"),
        ("21", "tlauncher-java:21"),
        ("25", "tlauncher-java:25"),
        (25, "tlauncher-java:25"),
        ("17", "tlauncher-java:21"),
    ],
)
def test_image_tag(java, tag):
    assert container.image_tag(java) == tag


def test_build_image_command():
    assert container.build_image_command("podman", "25") == [
        "podman",
        "build",
        "--pull",
        "--build-arg",
        "JAVA_VERSION=25",
        "-t",
        "tlauncher-java:25",
        "-f",
        "Containerfile",
        ".",
    ]


def test_build_image_command_normalises_java():
    cmd = container.build_image_command("docker", "11")
    assert cmd[0] == "docker"
    assert "JAVA_VERSION=21" in cmd
    assert cmd[cmd.index("-t") + 1] == "tlauncher-java:21"
