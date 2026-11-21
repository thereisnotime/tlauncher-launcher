import subprocess

from core import version


def test_app_version_reads_pyproject():
    import re
    from pathlib import Path

    text = (Path(__file__).parent.parent / "pyproject.toml").read_text()
    expected = re.search(r'^version = "([^"]+)"', text, re.M).group(1)
    assert version.app_version() == expected
    assert re.fullmatch(r"\d+\.\d+\.\d+", expected)


def test_version_string_with_and_without_git(monkeypatch):
    version.version_string.cache_clear()
    monkeypatch.setattr(version, "git_commit", lambda: "abc1234-dirty")
    assert version.version_string() == f"{version.app_version()} (abc1234-dirty)"
    version.version_string.cache_clear()
    monkeypatch.setattr(version, "git_commit", lambda: "")
    assert version.version_string() == version.app_version()
    version.version_string.cache_clear()


def test_git_commit_handles_missing_git(monkeypatch):
    def boom(*_a, **_k):
        raise FileNotFoundError("git")

    monkeypatch.setattr(subprocess, "run", boom)
    assert version.git_commit() == ""
