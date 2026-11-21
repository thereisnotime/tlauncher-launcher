import hashlib

import pytest

from core import compose_installer as ci

ASSET = "docker-compose-linux-x86_64"
PAYLOAD = b"\x7fELF fake docker compose binary" * 1000


@pytest.mark.parametrize(
    ("machine", "asset"),
    [
        ("x86_64", "docker-compose-linux-x86_64"),
        ("amd64", "docker-compose-linux-x86_64"),
        ("AMD64", "docker-compose-linux-x86_64"),
        ("aarch64", "docker-compose-linux-aarch64"),
        ("arm64", "docker-compose-linux-aarch64"),
        ("armv7l", "docker-compose-linux-armv7"),
        ("armv7", "docker-compose-linux-armv7"),
    ],
)
def test_asset_name(machine, asset):
    assert ci.asset_name(machine) == asset


def test_asset_name_unknown_arch():
    with pytest.raises(ValueError, match="riscv64"):
        ci.asset_name("riscv64")


def test_asset_name_defaults_to_this_machine(monkeypatch):
    monkeypatch.setattr(ci.platform, "machine", lambda: "aarch64")
    assert ci.asset_name() == "docker-compose-linux-aarch64"


def test_default_target_under_home(fake_home):
    assert ci.default_target() == fake_home / ".local" / "bin" / "docker-compose"


@pytest.fixture
def release(http_server, monkeypatch):
    monkeypatch.setattr(ci.platform, "system", lambda: "Linux")

    def publish(payload=PAYLOAD, digest=None):
        digest = digest if digest is not None else hashlib.sha256(payload).hexdigest()
        http_server.add(f"/rel/{ASSET}", payload)
        http_server.add(f"/rel/{ASSET}.sha256", f"{digest}  {ASSET}\n", "text/plain")
        return http_server.url("/rel")

    return publish


def install(base_url, target):
    logs = []
    res = ci.install_docker_compose(target, log=logs.append, base_url=base_url, machine="x86_64")
    return res, logs


def test_install_ok(release, tmp_path):
    target = tmp_path / "bin" / "docker-compose"
    res, logs = install(release(), target)
    assert res.ok, res.message
    assert res.path == target
    assert target.read_bytes() == PAYLOAD
    assert target.stat().st_mode & 0o777 == 0o755
    assert sorted(p.name for p in target.parent.iterdir()) == ["docker-compose"]
    assert "Checksum OK" in logs


def test_install_checksum_mismatch_leaves_nothing(release, tmp_path):
    target = tmp_path / "bin" / "docker-compose"
    res, _ = install(release(digest="0" * 64), target)
    assert not res.ok
    assert "Checksum mismatch" in res.message
    assert list(target.parent.iterdir()) == []


def test_install_mismatch_keeps_existing_binary(release, tmp_path):
    target = tmp_path / "bin" / "docker-compose"
    target.parent.mkdir()
    target.write_bytes(b"old working binary")
    res, _ = install(release(digest="f" * 64), target)
    assert not res.ok
    assert target.read_bytes() == b"old working binary"
    assert sorted(p.name for p in target.parent.iterdir()) == ["docker-compose"]


def test_install_bad_checksum_file(release, tmp_path):
    target = tmp_path / "bin" / "docker-compose"
    res, _ = install(release(digest="<html>nope</html>"), target)
    assert not res.ok
    assert "Unexpected checksum" in res.message
    assert list(target.parent.iterdir()) == []


def test_install_http_404(release, http_server, tmp_path):
    release()
    target = tmp_path / "bin" / "docker-compose"
    res, _ = install(http_server.url("/missing"), target)
    assert not res.ok
    assert "HTTP 404" in res.message
    assert not target.exists()


def test_install_binary_missing_after_checksum(http_server, monkeypatch, tmp_path):
    monkeypatch.setattr(ci.platform, "system", lambda: "Linux")
    http_server.add(f"/rel/{ASSET}.sha256", f"{'a' * 64}  {ASSET}\n", "text/plain")
    target = tmp_path / "bin" / "docker-compose"
    res, _ = install(http_server.url("/rel"), target)
    assert not res.ok
    assert "HTTP 404" in res.message
    assert list(target.parent.iterdir()) == []  # temp file cleaned up


def test_install_refuses_non_linux(monkeypatch, tmp_path):
    monkeypatch.setattr(ci.platform, "system", lambda: "Darwin")
    res = ci.install_docker_compose(
        tmp_path / "dc", base_url="http://127.0.0.1:9", machine="x86_64"
    )
    assert not res.ok
    assert "Linux" in res.message


def test_install_unknown_arch(monkeypatch, tmp_path):
    monkeypatch.setattr(ci.platform, "system", lambda: "Linux")
    res = ci.install_docker_compose(tmp_path / "dc", base_url="http://127.0.0.1:9", machine="s390x")
    assert not res.ok
    assert "s390x" in res.message
