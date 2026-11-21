import subprocess

from core import version


def test_app_version_reads_pyproject():
    assert version.app_version() == "1.1.0"


def test_version_string_with_and_without_git(monkeypatch):
    version.version_string.cache_clear()
    monkeypatch.setattr(version, "git_commit", lambda: "abc1234-dirty")
    assert version.version_string() == "1.1.0 (abc1234-dirty)"
    version.version_string.cache_clear()
    monkeypatch.setattr(version, "git_commit", lambda: "")
    assert version.version_string() == "1.1.0"
    version.version_string.cache_clear()


def test_git_commit_handles_missing_git(monkeypatch):
    def boom(*_a, **_k):
        raise FileNotFoundError("git")

    monkeypatch.setattr(subprocess, "run", boom)
    assert version.git_commit() == ""
