"""Tests for core/packs.py. It unpacks untrusted archives, so most of this is about
making sure nothing lands outside the target home directory."""

import hashlib
import json
import stat
import zipfile

import pytest

from core import packs
from core.packs import PackError

MC = "1.21.1"
FABRIC = "0.16.5"
VID = f"fabric-loader-{FABRIC}-{MC}"
JAR = "application/java-archive"


# ── helpers ──────────────────────────────────────────────────────────────────


def symlink_info(name):
    info = zipfile.ZipInfo(name)
    info.external_attr = (stat.S_IFLNK | 0o777) << 16
    return info


def make_zip(path, entries):
    """entries: {name: bytes|str} or list of (name|ZipInfo, data)."""
    items = entries.items() if isinstance(entries, dict) else entries
    with zipfile.ZipFile(path, "w") as zf:
        for name, data in items:
            zf.writestr(name, data)
    return path


def all_files(root):
    return sorted(p.relative_to(root).as_posix() for p in root.rglob("*") if p.is_file())


def outside_files(tmp_path, home):
    """Files anywhere under tmp_path that aren't inside home or the test inputs."""
    out = []
    for p in tmp_path.rglob("*"):
        if not p.is_file() or home in p.parents:
            continue
        if "inputs" in p.relative_to(tmp_path).parts or "user-home" in p.parts:
            continue
        out.append(p.relative_to(tmp_path).as_posix())
    return out


def profiles(home):
    return json.loads((home / "launcher_profiles.json").read_text())["profiles"]


@pytest.fixture
def inputs(tmp_path):
    d = tmp_path / "inputs"
    d.mkdir()
    return d


@pytest.fixture
def home(tmp_path):
    h = tmp_path / "mc" / "home"
    h.mkdir(parents=True)
    return h


@pytest.fixture
def loader_home(home):
    """A home where the fabric version for the test packs is already installed,
    so ensure_loader() never goes to the network."""
    vdir = home / "versions" / VID
    vdir.mkdir(parents=True)
    (vdir / f"{VID}.json").write_text(json.dumps({"id": VID, "inheritsFrom": MC}))
    return home


# ── safe_join ────────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("rel", "expected"),
    [
        ("mods/a.jar", "mods/a.jar"),
        ("./mods//a.jar", "mods/a.jar"),
        ("config\\sub\\x.toml", "config/sub/x.toml"),
        ("servers.dat", "servers.dat"),
    ],
)
def test_safe_join_accepts(tmp_path, rel, expected):
    assert packs.safe_join(tmp_path, rel) == (tmp_path / expected).resolve()


@pytest.mark.parametrize(
    "rel",
    [
        "../x",
        "a/../../x",
        "a/../b",
        "..\\..\\x",
        "/etc/passwd",
        "\\\\server\\share\\x",
        "C:/Windows/x",
        "c:x",
        "D:\\x",
        "",
        ".",
        "./",
    ],
)
def test_safe_join_rejects(tmp_path, rel):
    with pytest.raises(PackError):
        packs.safe_join(tmp_path, rel)


def test_safe_join_rejects_symlinked_dir_escape(tmp_path):
    root = tmp_path / "root"
    root.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    (root / "link").symlink_to(outside)
    with pytest.raises(PackError):
        packs.safe_join(root, "link/x.jar")


@pytest.mark.parametrize(
    ("value", "expected"),
    [("fabric-loader-0.16-1.21", "fabric-loader-0.16-1.21"), ("../../x", "_.._x"), ("..", "")],
)
def test_safe_name(value, expected):
    assert packs._safe_name(value) == expected
    assert "/" not in packs._safe_name(value)


# ── container paths ──────────────────────────────────────────────────────────


def test_container_and_host_path_round_trip(home):
    sub = home / "versions" / VID
    cpath = packs.container_path(home, sub)
    assert cpath == f"/home/app/.minecraft/versions/{VID}"
    assert packs.host_path(home, cpath) == sub.resolve()
    assert packs.container_path(home, home) == "/home/app/.minecraft"
    assert packs.host_path(home, "/home/app/.minecraft") == home


@pytest.mark.parametrize(
    "game_dir", ["", "/somewhere/else", "/home/app/.minecraft/../../etc", "/home/app/.minecraftX"]
)
def test_host_path_rejects_foreign_paths(home, game_dir):
    assert packs.host_path(home, game_dir) is None


# ── detect_kind ──────────────────────────────────────────────────────────────


def test_detect_kind(inputs):
    mr = make_zip(inputs / "a.zip", {"modrinth.index.json": "{}", "mods/x.jar": "j"})
    prof = make_zip(inputs / "b.zip", {"profile_metadata.json": "{}", "gamedata/mods/x.jar": "j"})
    mods = make_zip(inputs / "c.bin", {"Pack/mods/x.JAR": "j"})
    assert packs.detect_kind(mr) == "mrpack"
    assert packs.detect_kind(prof) == "mcprofile"
    assert packs.detect_kind(mods) == "mods"


def test_detect_kind_rejects(inputs):
    junk = make_zip(inputs / "junk.zip", {"readme.txt": "hi"})
    with pytest.raises(PackError, match="Unrecognised"):
        packs.detect_kind(junk)
    notzip = inputs / "x.mrpack"
    notzip.write_text("<html>login page</html>")
    with pytest.raises(PackError, match="Not a zip"):
        packs.detect_kind(notzip)


# ── _mods_zip_layout ─────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("names", "expected"),
    [
        # Wrapper folder stripped.
        (
            ["MyPack/", "MyPack/mods/a.jar", "MyPack/config/a.toml", "MyPack/readme.txt"],
            {"MyPack/mods/a.jar": "mods/a.jar", "MyPack/config/a.toml": "config/a.toml"},
        ),
        # Wrapper with jars straight inside.
        (["Pack/a.jar", "Pack/b.jar"], {"Pack/a.jar": "mods/a.jar", "Pack/b.jar": "mods/b.jar"}),
        # Bare jars at the top level; non-jar files ignored.
        (
            ["a.jar", "B.JAR", "notes.txt"],
            {"a.jar": "mods/a.jar", "B.JAR": "mods/B.JAR"},
        ),
        # A single top-level game folder is not treated as a wrapper.
        (
            ["mods/a.jar", "mods/b.jar"],
            {"mods/a.jar": "mods/a.jar", "mods/b.jar": "mods/b.jar"},
        ),
        # config/ and friends kept as-is, deep jars flattened into mods/.
        (
            ["config/x/y.json", "resourcepacks/rp.zip", "stuff/deep/c.jar", "top.txt"],
            {
                "config/x/y.json": "config/x/y.json",
                "resourcepacks/rp.zip": "resourcepacks/rp.zip",
                "stuff/deep/c.jar": "mods/c.jar",
            },
        ),
        # Nothing usable.
        (["docs/readme.md", "x.txt"], {}),
    ],
)
def test_mods_zip_layout(names, expected):
    assert packs._mods_zip_layout(names) == expected


# ── import_mods_zip ──────────────────────────────────────────────────────────


def test_import_mods_zip_into_shared_folder(inputs, home):
    z = make_zip(
        inputs / "mods.zip",
        {"Pack/mods/a.jar": "A", "Pack/config/a.toml": "cfg", "Pack/extra.jar": "E"},
    )
    res = packs.import_mods_zip(z, home)
    assert res.kind == "mods"
    assert res.game_dir == home
    assert res.files == 3
    assert all_files(home) == ["config/a.toml", "mods/a.jar", "mods/extra.jar"]
    assert (home / "mods" / "a.jar").read_text() == "A"
    assert not (home / "launcher_profiles.json").exists()


def test_import_mods_zip_into_version(inputs, loader_home):
    z = make_zip(inputs / "mods.zip", {"a.jar": "A"})
    res = packs.import_mods_zip(z, loader_home, target_version=VID)
    assert res.version_id == VID
    assert (loader_home / "versions" / VID / "mods" / "a.jar").read_text() == "A"
    (prof,) = profiles(loader_home).values()
    assert prof["lastVersionId"] == VID
    assert prof["gameDir"] == f"/home/app/.minecraft/versions/{VID}"


def test_import_mods_zip_unknown_version(inputs, home):
    z = make_zip(inputs / "mods.zip", {"a.jar": "A"})
    with pytest.raises(PackError, match="not installed"):
        packs.import_mods_zip(z, home, target_version="1.99")


def test_import_mods_zip_version_traversal_sanitised(inputs, home, tmp_path):
    z = make_zip(inputs / "mods.zip", {"a.jar": "A"})
    (tmp_path / "mc" / "x").mkdir()  # what "../../x" would point at
    with pytest.raises(PackError, match="not installed"):
        packs.import_mods_zip(z, home, target_version="../../x")
    assert outside_files(tmp_path, home) == []


def test_import_mods_zip_no_mods(inputs, home):
    z = make_zip(inputs / "x.zip", {"docs/readme.md": "hi"})
    with pytest.raises(PackError, match="No mods"):
        packs.import_mods_zip(z, home)


def test_import_mods_zip_slip_rejected(inputs, home, tmp_path):
    z = make_zip(inputs / "evil.zip", {"mods/../../../evil.jar": "pwn"})
    with pytest.raises(PackError):
        packs.import_mods_zip(z, home)
    assert outside_files(tmp_path, home) == []


def test_import_mods_zip_skips_symlinks(inputs, home, tmp_path):
    z = make_zip(
        inputs / "evil.zip",
        [(symlink_info("mods/link.jar"), "/etc/passwd"), ("mods/ok.jar", "ok")],
    )
    packs.import_mods_zip(z, home)
    assert not (home / "mods" / "link.jar").exists()
    assert not (home / "mods" / "link.jar").is_symlink()
    assert (home / "mods" / "ok.jar").read_text() == "ok"


# ── import_mcprofile ─────────────────────────────────────────────────────────


def mcprofile(path, version_id=VID, profile=None, extra=()):
    meta = {
        "profile_id": "p",
        "profile_data": profile if profile is not None else {"name": "My Pack"},
        "version_id": version_id,
    }
    entries = [("profile_metadata.json", json.dumps(meta))]
    entries += list(extra)
    return make_zip(path, entries)


def test_import_mcprofile(inputs, home):
    z = mcprofile(
        inputs / "p.mcprofile.zip",
        extra=[
            (f"version/{VID}.json", '{"id": "x"}'),
            ("gamedata/mods/a.jar", "A"),
            ("gamedata/config/a.toml", "cfg"),
        ],
    )
    res = packs.import_mcprofile(z, home)
    vdir = home / "versions" / VID
    assert res.kind == "mcprofile"
    assert res.name == "My Pack"
    assert res.files == 3
    assert all_files(vdir) == sorted([f"{VID}.json", "config/a.toml", "mods/a.jar"])
    (prof,) = profiles(home).values()
    assert prof["name"] == "My Pack"
    assert prof["gameDir"] == f"/home/app/.minecraft/versions/{VID}"


def test_import_mcprofile_without_gamedata_has_no_game_dir(inputs, home):
    z = mcprofile(inputs / "p.zip", version_id=MC, extra=[(f"version/{MC}.json", "{}")])
    packs.import_mcprofile(z, home)
    (prof,) = profiles(home).values()
    assert "gameDir" not in prof
    assert prof["lastVersionId"] == MC


def test_import_mcprofile_needs_version(inputs, home):
    z = mcprofile(inputs / "p.zip", version_id="", profile={})
    with pytest.raises(PackError, match="no version id"):
        packs.import_mcprofile(z, home)


def test_import_mcprofile_version_id_traversal(inputs, home, tmp_path):
    z = mcprofile(inputs / "p.zip", version_id="../../x", extra=[("version/x.json", "{}")])
    res = packs.import_mcprofile(z, home)
    assert "/" not in res.version_id
    assert (home / "versions" / res.version_id).parent == home / "versions"
    assert outside_files(tmp_path, home) == []


@pytest.mark.parametrize(
    "evil",
    [
        "gamedata/../../../../evil.txt",
        "version/../../../evil.txt",
        "gamedata//abs/evil.txt",
        "gamedata/C:/evil.txt",
    ],
)
def test_import_mcprofile_zip_slip(inputs, home, tmp_path, evil):
    z = mcprofile(inputs / "p.zip", extra=[(evil, "pwn")])
    with pytest.raises(PackError):
        packs.import_mcprofile(z, home)
    assert outside_files(tmp_path, home) == []


def test_import_mcprofile_symlink_entries_skipped(inputs, home, tmp_path):
    outside = tmp_path / "outside"
    outside.mkdir()
    z = mcprofile(
        inputs / "p.zip",
        extra=[
            (symlink_info("gamedata/mods"), str(outside)),
            ("gamedata/mods/pwn.jar", "pwn"),
        ],
    )
    packs.import_mcprofile(z, home)
    mods = home / "versions" / VID / "mods"
    assert not mods.is_symlink()
    assert (mods / "pwn.jar").read_text() == "pwn"
    assert list(outside.iterdir()) == []


# ── resolve_share_url / download ─────────────────────────────────────────────


@pytest.mark.parametrize(
    ("url", "expected"),
    [
        (
            "https://drive.google.com/file/d/AbC_12-x/view?usp=sharing",
            "https://drive.usercontent.google.com/download?id=AbC_12-x&export=download&confirm=t",
        ),
        (
            "https://drive.google.com/open?id=XYZ",
            "https://drive.usercontent.google.com/download?id=XYZ&export=download&confirm=t",
        ),
        (
            "https://drive.google.com/uc?id=XYZ&export=download",
            "https://drive.usercontent.google.com/download?id=XYZ&export=download&confirm=t",
        ),
        (
            "https://www.dropbox.com/s/abc/pack.mrpack?dl=0",
            "https://www.dropbox.com/s/abc/pack.mrpack?dl=1",
        ),
        (
            "https://www.dropbox.com/scl/fi/abc/pack.zip?rlkey=k&raw=1",
            "https://www.dropbox.com/scl/fi/abc/pack.zip?rlkey=k&dl=1",
        ),
        (
            "https://github.com/me/packs/blob/main/dir/pack.mrpack",
            "https://raw.githubusercontent.com/me/packs/main/dir/pack.mrpack",
        ),
        (
            "https://github.com/me/packs/releases/download/v1/pack.mrpack",
            "https://github.com/me/packs/releases/download/v1/pack.mrpack",
        ),
        ("  https://cdn.modrinth.com/x.mrpack  ", "https://cdn.modrinth.com/x.mrpack"),
    ],
)
def test_resolve_share_url(url, expected):
    assert packs.resolve_share_url(url) == expected


def test_download_ok_with_hash(http_server, tmp_path):
    data = b"jar bytes"
    url = http_server.add("/a.jar", data, JAR)
    dest = tmp_path / "out" / "a.jar"
    packs.download(url, dest, hashes={"sha1": hashlib.sha1(data).hexdigest()}, size=len(data))
    assert dest.read_bytes() == data
    assert all_files(dest.parent) == ["a.jar"]


def test_download_refuses_html(http_server, tmp_path):
    url = http_server.add("/share", b"<html>sign in</html>", "text/html; charset=utf-8")
    dest = tmp_path / "out" / "pack.zip"
    with pytest.raises(PackError, match="web page"):
        packs.download(url, dest)
    assert all_files(dest.parent) == []


def test_download_size_mismatch(http_server, tmp_path):
    url = http_server.add("/a.jar", b"1234", JAR)
    dest = tmp_path / "a.jar"
    with pytest.raises(PackError, match="Size mismatch"):
        packs.download(url, dest, size=5)
    assert not dest.exists()
    assert not dest.with_name("a.jar.part").exists()


def test_download_http_error(http_server, tmp_path):
    with pytest.raises(PackError, match="Download failed"):
        packs.download(http_server.url("/nope"), tmp_path / "x")
    assert all_files(tmp_path) == []


@pytest.mark.parametrize("url", ["file:///etc/passwd", "ftp://x/y", "/etc/passwd"])
def test_download_rejects_non_http(tmp_path, url):
    with pytest.raises(PackError, match="Not an http"):
        packs.download(url, tmp_path / "x")


def test_fetch_source_local_and_missing(inputs, tmp_path):
    f = make_zip(inputs / "a.zip", {"a.jar": "A"})
    assert packs.fetch_source(str(f), tmp_path) == f
    with pytest.raises(PackError, match="not found"):
        packs.fetch_source(str(inputs / "missing.zip"), tmp_path)


# ── import_mrpack ────────────────────────────────────────────────────────────


def hashes_for(data, algos=("sha1", "sha512")):
    return {a: hashlib.new(a, data).hexdigest() for a in algos}


def mr_file(path, url, data, algos=("sha1", "sha512"), **extra):
    entry = {"path": path, "hashes": hashes_for(data, algos), "downloads": [url]}
    entry["fileSize"] = len(data)
    entry.update(extra)
    return entry


def make_mrpack(path, files, extra=(), deps=None, name="Test Pack", **index_extra):
    index = {
        "formatVersion": 1,
        "game": "minecraft",
        "versionId": "1.0.0",
        "name": name,
        "files": files,
        "dependencies": deps if deps is not None else {"minecraft": MC, "fabric-loader": FABRIC},
    }
    index.update(index_extra)
    return make_zip(path, [("modrinth.index.json", json.dumps(index)), *extra])


def run_mrpack(path, home, tmp_path, **kw):
    work = tmp_path / "work"
    work.mkdir(exist_ok=True)
    return packs.import_mrpack(path, home, "podman", "tlauncher-java:21", work, **kw)


@pytest.fixture
def no_network_loader(monkeypatch):
    """ensure_loader must short-circuit on the pre-created version json."""

    def boom(*_a, **_kw):
        raise AssertionError("loader installer must not run")

    monkeypatch.setattr(packs, "run_installer_in_container", boom)


def test_import_mrpack_happy_path(http_server, inputs, loader_home, tmp_path, no_network_loader):
    a, b = b"mod A", b"mod B"
    files = [
        mr_file("mods/a.jar", http_server.add("/a.jar", a, JAR), a, algos=("sha1",)),
        mr_file("mods/b.jar", http_server.add("/b.jar", b, JAR), b, algos=("sha512",)),
        mr_file(
            "mods/server-only.jar",
            http_server.url("/server-only.jar"),
            b"srv",
            env={"client": "unsupported", "server": "required"},
        ),
        mr_file(
            "mods/optional.jar",
            http_server.add("/opt.jar", b"opt", JAR),
            b"opt",
            env={"client": "optional", "server": "unsupported"},
        ),
    ]
    pack = make_mrpack(
        inputs / "pack.mrpack",
        files,
        extra=[
            ("overrides/config/a.toml", "cfg"),
            ("overrides/servers.dat", "servers"),
            ("client-overrides/options.txt", "opts"),
            (symlink_info("overrides/mods/link.jar"), "/etc/passwd"),
        ],
    )
    logs = []
    res = run_mrpack(pack, loader_home, tmp_path, log=logs.append)

    gdir = loader_home / "versions" / VID
    assert res.kind == "mrpack"
    assert res.version_id == VID
    assert res.game_dir == gdir
    assert res.files == 6
    assert all_files(gdir) == sorted(
        [
            f"{VID}.json",
            packs.MANIFEST_NAME,
            "config/a.toml",
            "mods/a.jar",
            "mods/b.jar",
            "mods/optional.jar",
            "options.txt",
            "servers.dat",
        ]
    )
    assert (gdir / "mods" / "a.jar").read_bytes() == a
    assert "/server-only.jar" not in http_server.requests
    manifest = json.loads((gdir / packs.MANIFEST_NAME).read_text())
    assert manifest["name"] == "Test Pack"
    assert "mods/a.jar" in manifest["files"]
    assert "options.txt" in manifest["files"]
    # servers.dat is also offered in the shared folder when it has none.
    assert (loader_home / "servers.dat").read_text() == "servers"
    (prof,) = profiles(loader_home).values()
    assert prof["name"] == "Test Pack"
    assert prof["lastVersionId"] == VID
    assert prof["gameDir"] == f"/home/app/.minecraft/versions/{VID}"


@pytest.mark.parametrize("algo", ["sha1", "sha512"])
def test_import_mrpack_wrong_hash_fails_and_leaves_nothing(
    http_server, inputs, loader_home, tmp_path, algo
):
    data = b"tampered"
    entry = mr_file("mods/a.jar", http_server.add("/a.jar", data, JAR), data, algos=(algo,))
    entry["hashes"][algo] = "0" * len(entry["hashes"][algo])
    pack = make_mrpack(inputs / "p.mrpack", [entry])
    with pytest.raises(PackError, match="Could not download a.jar"):
        run_mrpack(pack, loader_home, tmp_path)
    assert all_files(loader_home) == [f"versions/{VID}/{VID}.json"]
    assert not (loader_home / "launcher_profiles.json").exists()


def test_import_mrpack_falls_back_to_next_mirror(http_server, inputs, loader_home, tmp_path):
    good = b"good jar"
    http_server.add("/bad.jar", b"evil jar", JAR)
    http_server.add("/good.jar", good, JAR)
    entry = mr_file("mods/a.jar", "", good)
    entry["downloads"] = [http_server.url("/bad.jar"), http_server.url("/good.jar")]
    entry.pop("fileSize")
    pack = make_mrpack(inputs / "p.mrpack", [entry])
    run_mrpack(pack, loader_home, tmp_path)
    assert (loader_home / "versions" / VID / "mods" / "a.jar").read_bytes() == good


@pytest.mark.parametrize("evil", ["../x.jar", "../../../x.jar", "/tmp/x.jar", "C:/x.jar", ""])
def test_import_mrpack_file_path_traversal(http_server, inputs, loader_home, tmp_path, evil):
    data = b"pwn"
    entry = mr_file(evil, http_server.add("/x.jar", data, JAR), data)
    pack = make_mrpack(inputs / "p.mrpack", [entry])
    with pytest.raises(PackError):
        run_mrpack(pack, loader_home, tmp_path)
    assert http_server.requests == []
    assert outside_files(tmp_path, loader_home) == []
    assert all_files(loader_home) == [f"versions/{VID}/{VID}.json"]


@pytest.mark.parametrize(
    "evil", ["overrides/../../../evil.txt", "client-overrides/../../x.txt", "overrides//abs.txt"]
)
def test_import_mrpack_override_traversal(inputs, loader_home, tmp_path, evil):
    pack = make_mrpack(inputs / "p.mrpack", [], extra=[(evil, "pwn")])
    with pytest.raises(PackError):
        run_mrpack(pack, loader_home, tmp_path)
    assert outside_files(tmp_path, loader_home) == []


def test_import_mrpack_reimport_removes_dropped_files(http_server, inputs, loader_home, tmp_path):
    a, b = b"mod A", b"mod B"
    fa = mr_file("mods/a.jar", http_server.add("/a.jar", a, JAR), a)
    fb = mr_file("mods/b.jar", http_server.add("/b.jar", b, JAR), b)
    v1 = make_mrpack(inputs / "v1.mrpack", [fa, fb], extra=[("overrides/config/old.toml", "o")])
    run_mrpack(v1, loader_home, tmp_path)
    gdir = loader_home / "versions" / VID
    (gdir / "mods" / "user-added.jar").write_text("mine")
    assert http_server.requests == ["/a.jar", "/b.jar"]

    v2 = make_mrpack(inputs / "v2.mrpack", [fa], extra=[("overrides/config/new.toml", "n")])
    logs = []
    res = run_mrpack(v2, loader_home, tmp_path, log=logs.append)

    assert all_files(gdir) == sorted(
        [
            f"{VID}.json",
            packs.MANIFEST_NAME,
            "config/new.toml",
            "mods/a.jar",
            "mods/user-added.jar",
        ]
    )
    # a.jar was already up to date, so it wasn't downloaded again.
    assert http_server.requests == ["/a.jar", "/b.jar"]
    assert any("up to date" in line for line in logs)
    assert res.files == 2
    manifest = json.loads((gdir / packs.MANIFEST_NAME).read_text())
    assert manifest["files"] == ["config/new.toml", "mods/a.jar"]
    assert len(profiles(loader_home)) == 1


def test_import_mrpack_vanilla_uses_mc_version(inputs, home, tmp_path):
    pack = make_mrpack(inputs / "p.mrpack", [], deps={"minecraft": MC})
    res = run_mrpack(pack, home, tmp_path)
    assert res.version_id == MC
    assert (home / "versions" / MC).is_dir()


@pytest.mark.parametrize(
    ("index_extra", "deps", "msg"),
    [
        ({"formatVersion": 2}, None, "Unsupported"),
        ({"game": "terraria"}, None, "Unsupported"),
        ({}, {"fabric-loader": FABRIC}, "no minecraft"),
    ],
)
def test_import_mrpack_rejects_bad_index(inputs, home, tmp_path, index_extra, deps, msg):
    pack = make_mrpack(inputs / "p.mrpack", [], deps=deps, **index_extra)
    with pytest.raises(PackError, match=msg):
        run_mrpack(pack, home, tmp_path)


def test_import_archive_dispatches(inputs, home):
    z = make_zip(inputs / "mods.zip", {"a.jar": "A"})
    seen = []

    def choose(versions):
        seen.append(versions)
        return ""

    res = packs.import_archive(str(z), home=home, choose_target=choose)
    assert res.kind == "mods"
    assert seen == [[]]
    assert (home / "mods" / "a.jar").exists()


def test_import_archive_cancelled(inputs, home):
    z = make_zip(inputs / "mods.zip", {"a.jar": "A"})
    with pytest.raises(PackError, match="cancelled"):
        packs.import_archive(str(z), home=home, choose_target=lambda _v: None)
    assert all_files(home) == []


# ── export_profile ───────────────────────────────────────────────────────────


def write_profiles(home, profs):
    (home / "launcher_profiles.json").write_text(json.dumps({"profiles": profs}))


def zip_names(path):
    with zipfile.ZipFile(path) as zf:
        return sorted(zf.namelist())


def test_export_profile_without_game_dir_includes_shared(home, tmp_path):
    write_profiles(home, {"vanilla": {"name": "Vanilla", "lastVersionId": MC}})
    vdir = home / "versions" / MC
    vdir.mkdir(parents=True)
    (vdir / f"{MC}.json").write_text("{}")
    (home / "mods").mkdir()
    (home / "mods" / "a.jar").write_text("A")
    (home / "config").mkdir()
    (home / "config" / "c.toml").write_text("c")
    (home / "saves" / "World").mkdir(parents=True)
    (home / "saves" / "World" / "level.dat").write_text("w")

    out = packs.export_profile("vanilla", tmp_path / "v.mcprofile.zip", home=home)
    assert zip_names(out) == [
        "gamedata/config/c.toml",
        "gamedata/mods/a.jar",
        "profile_metadata.json",
        f"version/{MC}.json",
    ]
    with zipfile.ZipFile(out) as zf:
        meta = json.loads(zf.read("profile_metadata.json"))
    assert meta["version_id"] == MC
    assert meta["profile_data"]["name"] == "Vanilla"


def test_export_profile_with_own_folder_excludes_shared(loader_home, tmp_path):
    gdir = loader_home / "versions" / VID
    (gdir / "mods").mkdir()
    (gdir / "mods" / "own.jar").write_text("own")
    (loader_home / "mods").mkdir()
    (loader_home / "mods" / "shared.jar").write_text("shared")
    write_profiles(
        loader_home,
        {
            "fab": {
                "name": "Fabric",
                "lastVersionId": VID,
                "gameDir": f"/home/app/.minecraft/versions/{VID}",
            }
        },
    )
    out = packs.export_profile("fab", tmp_path / "f.zip", home=loader_home)
    assert zip_names(out) == [
        "profile_metadata.json",
        f"version/{VID}.json",
        "version/mods/own.jar",
    ]


def test_export_profile_with_separate_game_dir(loader_home, tmp_path):
    inst = loader_home / "instances" / "foo"
    (inst / "mods").mkdir(parents=True)
    (inst / "mods" / "x.jar").write_text("x")
    (loader_home / "mods").mkdir()
    (loader_home / "mods" / "shared.jar").write_text("shared")
    write_profiles(
        loader_home,
        {
            "foo": {
                "name": "Foo",
                "lastVersionId": VID,
                "gameDir": "/home/app/.minecraft/instances/foo",
            }
        },
    )
    out = packs.export_profile("foo", tmp_path / "foo.zip", home=loader_home)
    assert zip_names(out) == ["gamedata/mods/x.jar", "profile_metadata.json", f"version/{VID}.json"]


def test_export_profile_missing(home, tmp_path):
    write_profiles(home, {})
    with pytest.raises(PackError, match="not found"):
        packs.export_profile("nope", tmp_path / "x.zip", home=home)


def test_export_import_round_trip(home, tmp_path):
    write_profiles(home, {"vanilla": {"name": "Vanilla", "lastVersionId": MC}})
    (home / "versions" / MC).mkdir(parents=True)
    (home / "versions" / MC / f"{MC}.json").write_text('{"id": "1.21.1"}')
    (home / "mods").mkdir()
    (home / "mods" / "a.jar").write_bytes(b"A" * 100)
    (home / "config").mkdir()
    (home / "config" / "c.toml").write_text("c = 1")

    archive = packs.export_profile("vanilla", tmp_path / "v.mcprofile.zip", home=home)
    assert packs.detect_kind(archive) == "mcprofile"

    other = tmp_path / "other-home"
    other.mkdir()
    res = packs.import_mcprofile(archive, other)
    vdir = other / "versions" / MC
    assert res.version_id == MC
    assert res.name == "Vanilla"
    assert res.files == 3
    assert (vdir / f"{MC}.json").read_text() == '{"id": "1.21.1"}'
    assert (vdir / "mods" / "a.jar").read_bytes() == b"A" * 100
    assert (vdir / "config" / "c.toml").read_text() == "c = 1"
    (prof,) = profiles(other).values()
    assert prof["name"] == "Vanilla"
    assert prof["gameDir"] == f"/home/app/.minecraft/versions/{MC}"


# ── profiles / versions ──────────────────────────────────────────────────────


def test_upsert_profile_updates_by_name_and_avoids_id_clash(home):
    write_profiles(home, {"My_Pack": {"name": "Something else", "lastVersionId": "x"}})
    pid = packs.upsert_profile(home, "My Pack", MC, None)
    assert pid == "My_Pack_1"
    again = packs.upsert_profile(home, "My Pack", VID, home / "versions" / VID)
    assert again == pid
    profs = profiles(home)
    assert len(profs) == 2
    assert profs[pid]["lastVersionId"] == VID
    assert profs["My_Pack"]["lastVersionId"] == "x"


def test_list_modded_versions(loader_home):
    vanilla = loader_home / "versions" / MC
    vanilla.mkdir()
    (vanilla / f"{MC}.json").write_text('{"id": "1.21.1"}')
    broken = loader_home / "versions" / "broken"
    broken.mkdir()
    (broken / "broken.json").write_text("{not json")
    assert packs.list_modded_versions(loader_home) == [VID]
    assert packs.list_modded_versions(loader_home / "nope") == []
