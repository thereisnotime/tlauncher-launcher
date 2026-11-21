"""
Modpack / profile import and export.

Supported archives (detected by content, not by file name):
- Modrinth modpacks (.mrpack): installs the loader, downloads every mod with
  hash checks, applies overrides and adds a TLauncher profile.
- Profile archives (.mcprofile.zip) written by export_profile().
- Plain zips of mods: mods/*.jar (or bare .jar files), plus optional config/,
  resourcepacks/ and similar folders.

Everything is UI-agnostic: callers pass a `log` callable and, for plain mod
zips, the target version. Paths taken from archives are always validated so a
malicious archive can't write outside the game directory ("zip slip").
"""

import hashlib
import json
import os
import re
import shutil
import stat
import subprocess
import tempfile
import urllib.parse
import urllib.request
import zipfile
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Dict, List, Optional

# Repo-local Minecraft directory (mounted at CONTAINER_MC_DIR inside the container)
HOME_DIR = Path(__file__).resolve().parent.parent / "home"
CONTAINER_MC_DIR = "/home/app/.minecraft"

USER_AGENT = "tlauncher-launcher (https://github.com/thereisnotime/tlauncher-launcher)"
MANIFEST_NAME = ".mrpack-files.json"

# Top-level folders of a plain mods zip that are copied as-is into the game dir.
GAME_SUBDIRS = {
    "mods",
    "config",
    "defaultconfigs",
    "resourcepacks",
    "shaderpacks",
    "kubejs",
    "scripts",
}

Log = Callable[[str], None]


class PackError(Exception):
    """User-facing import/export error."""


@dataclass
class ImportResult:
    kind: str  # "mrpack" | "mcprofile" | "mods"
    name: str
    version_id: str = ""
    game_dir: Optional[Path] = None
    files: int = 0
    notes: List[str] = field(default_factory=list)


def _nolog(_msg: str) -> None:
    pass


def _rm(path: Path) -> None:
    try:
        Path(path).unlink()
    except FileNotFoundError:
        pass


# ── URLs and downloads ───────────────────────────────────────────────────────


def resolve_share_url(url: str) -> str:
    """Turn common "share"/"view" links into direct download links."""
    url = url.strip()
    parsed = urllib.parse.urlparse(url)
    host = parsed.netloc.lower()
    query = urllib.parse.parse_qs(parsed.query)

    if host in ("drive.google.com", "docs.google.com"):
        m = re.search(r"/file/d/([A-Za-z0-9_-]+)", parsed.path)
        file_id = m.group(1) if m else (query.get("id") or [""])[0]
        if file_id:
            return f"https://drive.usercontent.google.com/download?id={file_id}&export=download&confirm=t"

    if host.endswith("dropbox.com"):
        query["dl"] = ["1"]
        query.pop("raw", None)
        return urllib.parse.urlunparse(
            parsed._replace(query=urllib.parse.urlencode(query, doseq=True))
        )

    if host == "github.com":
        # https://github.com/o/r/blob/<ref>/path -> raw.githubusercontent.com/o/r/<ref>/path
        m = re.match(r"^/([^/]+)/([^/]+)/blob/(.+)$", parsed.path)
        if m:
            return f"https://raw.githubusercontent.com/{m.group(1)}/{m.group(2)}/{m.group(3)}"

    return url


def download(
    url: str,
    dest: Path,
    log: Log = _nolog,
    hashes: Optional[Dict[str, str]] = None,
    size: Optional[int] = None,
    timeout: int = 60,
) -> Path:
    """
    Download url to dest atomically. Verifies size and sha512/sha1 when given.
    Refuses HTML responses (share links that aren't public, login pages...).
    """
    if not url.lower().startswith(("http://", "https://")):
        raise PackError(f"Not an http(s) URL: {url}")

    dest = Path(dest)
    dest.parent.mkdir(parents=True, exist_ok=True)
    part = dest.with_name(dest.name + ".part")
    algo = None
    if hashes:
        algo = "sha512" if "sha512" in hashes else ("sha1" if "sha1" in hashes else None)
    digest = hashlib.new(algo) if algo else None

    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310 (checked above)
            ctype = resp.headers.get("Content-Type", "")
            if "text/html" in ctype:
                raise PackError(
                    "The link returned a web page instead of a file. Use a direct "
                    "download link, or make the shared file public."
                )
            with open(part, "wb") as out:
                while True:
                    chunk = resp.read(1 << 16)
                    if not chunk:
                        break
                    out.write(chunk)
                    if digest:
                        digest.update(chunk)
    except PackError:
        _rm(part)
        raise
    except Exception as e:
        _rm(part)
        raise PackError(f"Download failed ({url}): {e}") from e

    if size is not None and part.stat().st_size != size:
        _rm(part)
        raise PackError(f"Size mismatch for {dest.name} (expected {size} bytes)")
    if digest and digest.hexdigest().lower() != hashes[algo].lower():
        _rm(part)
        raise PackError(f"Checksum mismatch for {dest.name}; refusing to install it")

    Path(part).replace(dest)
    return dest


def fetch_source(source: str, workdir: Path, log: Log = _nolog) -> Path:
    """Return a local path for a file path or an http(s) URL (downloaded into workdir)."""
    if source.lower().startswith(("http://", "https://")):
        url = resolve_share_url(source)
        name = Path(urllib.parse.urlparse(url).path).name or "download.zip"
        name = _safe_name(name) or "download.zip"
        log(f"🌐 Downloading {url}")
        return download(url, Path(workdir) / name, log=log, timeout=120)
    path = Path(source).expanduser()
    if not path.is_file():
        raise PackError(f"File not found: {source}")
    return path


# ── Path safety ──────────────────────────────────────────────────────────────


def _safe_name(value: str) -> str:
    """A single safe path component (version ids, profile folders)."""
    value = re.sub(r"[^A-Za-z0-9._+-]", "_", str(value or "").strip())
    return value.lstrip(".")[:120]


def safe_join(root: Path, rel: str) -> Path:
    """Join an archive-relative path under root, rejecting anything that escapes it."""
    rel = rel.replace("\\", "/")
    if rel.startswith("/") or re.match(r"^[A-Za-z]:", rel):
        raise PackError(f"Unsafe absolute path in archive: {rel}")
    parts = [p for p in rel.split("/") if p not in ("", ".")]
    if not parts or any(p == ".." for p in parts):
        raise PackError(f"Unsafe path in archive: {rel}")
    root = Path(root).resolve()
    target = root.joinpath(*parts).resolve()
    if target != root and root not in target.parents:
        raise PackError(f"Unsafe path in archive: {rel}")
    return target


def _is_symlink(info: zipfile.ZipInfo) -> bool:
    return stat.S_ISLNK(info.external_attr >> 16)


def _write_member(zf: zipfile.ZipFile, info: zipfile.ZipInfo, target: Path) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    with zf.open(info) as src, open(target, "wb") as dst:
        shutil.copyfileobj(src, dst)


def _extract_prefix(zf: zipfile.ZipFile, prefix: str, root: Path, log: Log = _nolog) -> List[str]:
    """Extract every file under `prefix` into root. Returns root-relative paths written."""
    written = []
    for info in zf.infolist():
        if info.is_dir() or not info.filename.startswith(prefix) or _is_symlink(info):
            continue
        rel = info.filename[len(prefix) :]
        if not rel:
            continue
        target = safe_join(root, rel)
        _write_member(zf, info, target)
        written.append(target.relative_to(Path(root).resolve()).as_posix())
    return written


# ── Archive detection ────────────────────────────────────────────────────────


def detect_kind(path: Path) -> str:
    try:
        with zipfile.ZipFile(path) as zf:
            names = zf.namelist()
    except zipfile.BadZipFile as e:
        raise PackError("Not a zip/.mrpack archive") from e
    if "modrinth.index.json" in names:
        return "mrpack"
    if "profile_metadata.json" in names:
        return "mcprofile"
    if any(n.lower().endswith(".jar") for n in names):
        return "mods"
    raise PackError(
        "Unrecognised archive: expected a .mrpack, a .mcprofile.zip, or a zip with mod .jar files"
    )


# ── TLauncher profiles / versions ────────────────────────────────────────────


def container_path(home: Path, host_path: Path) -> str:
    rel = Path(host_path).resolve().relative_to(Path(home).resolve()).as_posix()
    return f"{CONTAINER_MC_DIR}/{rel}" if rel != "." else CONTAINER_MC_DIR


def host_path(home: Path, game_dir: str) -> Optional[Path]:
    """Map a profile's container gameDir back to a host path under home (or None)."""
    if not game_dir:
        return None
    if game_dir == CONTAINER_MC_DIR:
        return Path(home)
    prefix = CONTAINER_MC_DIR + "/"
    if not game_dir.startswith(prefix):
        return None
    try:
        return safe_join(home, game_dir[len(prefix) :])
    except PackError:
        return None


def _load_profiles(home: Path) -> dict:
    f = Path(home) / "launcher_profiles.json"
    if f.exists():
        with open(f) as fh:
            return json.load(fh)
    return {"profiles": {}}


def _save_profiles(home: Path, data: dict) -> None:
    f = Path(home) / "launcher_profiles.json"
    f.parent.mkdir(parents=True, exist_ok=True)
    tmp = f.with_suffix(".json.tmp")
    with open(tmp, "w") as fh:
        json.dump(data, fh, indent=2)
    tmp.replace(f)


def upsert_profile(home: Path, name: str, version_id: str, game_dir: Optional[Path]) -> str:
    """Add or update a TLauncher profile by name. Returns the profile id."""
    data = _load_profiles(home)
    profiles = data.setdefault("profiles", {})
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000Z")

    profile_id = next((pid for pid, p in profiles.items() if p.get("name") == name), None)
    if profile_id is None:
        base = _safe_name(name) or "imported"
        profile_id, n = base, 1
        while profile_id in profiles:
            profile_id, n = f"{base}_{n}", n + 1
        profiles[profile_id] = {"name": name, "type": "custom", "created": now}

    profile = profiles[profile_id]
    profile["lastVersionId"] = version_id
    profile["lastUsed"] = now
    if game_dir is not None:
        profile["gameDir"] = container_path(home, game_dir)
    _save_profiles(home, data)
    return profile_id


def list_modded_versions(home: Path = HOME_DIR) -> List[str]:
    """Installed loader versions (version json with inheritsFrom), newest first."""
    out = []
    versions = Path(home) / "versions"
    if not versions.is_dir():
        return out
    for d in versions.iterdir():
        j = d / f"{d.name}.json"
        if not j.is_file():
            continue
        try:
            with open(j) as fh:
                if json.load(fh).get("inheritsFrom"):
                    out.append(d.name)
        except (OSError, ValueError):
            continue
    return sorted(out, key=lambda n: Path(versions / n).stat().st_mtime, reverse=True)


# ── Loader installation ──────────────────────────────────────────────────────

LOADER_KEYS = ("neoforge", "forge", "fabric-loader", "quilt-loader")


def _installer_url(loader: str, mc: str, version: str) -> str:
    if loader == "neoforge":
        if mc == "1.20.1":  # NeoForge 1.20.1 was still published as "forge"
            return (
                "https://maven.neoforged.net/releases/net/neoforged/forge/"
                f"{mc}-{version}/forge-{mc}-{version}-installer.jar"
            )
        return (
            "https://maven.neoforged.net/releases/net/neoforged/neoforge/"
            f"{version}/neoforge-{version}-installer.jar"
        )
    return (
        "https://maven.minecraftforge.net/net/minecraftforge/forge/"
        f"{mc}-{version}/forge-{mc}-{version}-installer.jar"
    )


def _installer_version_id(installer: Path) -> str:
    with zipfile.ZipFile(installer) as zf:
        if "version.json" in zf.namelist():
            return json.loads(zf.read("version.json"))["id"]
        profile = json.loads(zf.read("install_profile.json"))
    return profile.get("version") or profile["install"]["target"]


def run_installer_in_container(
    installer: Path, home: Path, runtime: str, image: str, log: Log = _nolog
) -> None:
    """Run a Forge/NeoForge installer headlessly inside the launcher image."""
    home = Path(home).resolve()
    # The installer refuses to run without a launcher profile file.
    if not (home / "launcher_profiles.json").exists():
        _save_profiles(home, {"profiles": {}})

    cmd = [runtime, "run", "--rm", "--name", "tlauncher-loader-install"]
    if runtime == "podman":
        cmd += ["--userns=keep-id"]
    else:
        cmd += ["--user", f"{os.getuid()}:{os.getgid()}", "-e", "HOME=/tmp"]
    cmd += [
        "-v",
        f"{home}:{CONTAINER_MC_DIR}:Z",
        "-v",
        f"{installer.parent.resolve()}:/installer:ro,Z",
        image,
        "java",
        "-jar",
        f"/installer/{installer.name}",
        "--install-client",
        CONTAINER_MC_DIR,
    ]
    log(f"⚙ Running loader installer in {image} (downloads libraries, takes a minute)...")
    try:
        proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    except FileNotFoundError as e:
        raise PackError(f"'{runtime}' not found") from e
    tail: List[str] = []
    for line in proc.stdout:
        line = line.rstrip()
        tail = (tail + [line])[-15:]
        if any(k in line for k in ("Downloading", "Processor", "Successfully", "ERROR", "rror")):
            log(f"  {line[:160]}")
    if proc.wait() != 0:
        raise PackError("Loader installer failed:\n" + "\n".join(tail))


def ensure_loader(
    home: Path,
    mc: str,
    loader: str,
    loader_version: str,
    runtime: str,
    image: str,
    workdir: Path,
    log: Log = _nolog,
) -> str:
    """Make sure the version for (mc, loader) is installed. Returns its version id."""
    if not loader:
        return mc  # vanilla: TLauncher downloads it itself
    versions = Path(home) / "versions"

    if loader in ("fabric-loader", "quilt-loader"):
        vid = f"{loader}-{loader_version}-{mc}"
        if (versions / vid / f"{vid}.json").is_file():
            log(f"✓ {vid} already installed")
            return vid
        meta = (
            "https://meta.fabricmc.net/v2/versions/loader"
            if loader == "fabric-loader"
            else "https://meta.quiltmc.org/v3/versions/loader"
        )
        url = f"{meta}/{mc}/{loader_version}/profile/json"
        log(f"⚙ Installing {loader} {loader_version} for {mc}")
        tmp = download(url, Path(workdir) / "loader-profile.json", log=log)
        with open(tmp) as fh:
            profile = json.load(fh)
        vid = _safe_name(profile.get("id") or vid)
        target = versions / vid / f"{vid}.json"
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(tmp, target)
        return vid

    if loader in ("neoforge", "forge"):
        url = _installer_url(loader, mc, loader_version)
        installer = download(url, Path(workdir) / "installer" / Path(url).name, log=log)
        vid = _safe_name(_installer_version_id(installer))
        if (versions / vid / f"{vid}.json").is_file():
            log(f"✓ {vid} already installed")
            return vid
        run_installer_in_container(installer, home, runtime, image, log)
        if not (versions / vid / f"{vid}.json").is_file():
            raise PackError(f"Installer finished but {vid} was not created")
        log(f"✓ Installed {vid}")
        return vid

    raise PackError(f"Unsupported mod loader: {loader}")


# ── Importers ────────────────────────────────────────────────────────────────


def _file_matches(path: Path, hashes: Dict[str, str]) -> bool:
    if not path.is_file():
        return False
    algo = "sha512" if "sha512" in hashes else "sha1"
    if algo not in hashes:
        return False
    h = hashlib.new(algo)
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 16), b""):
            h.update(chunk)
    return h.hexdigest().lower() == hashes[algo].lower()


def import_mrpack(
    path: Path,
    home: Path,
    runtime: str,
    image: str,
    workdir: Path,
    log: Log = _nolog,
) -> ImportResult:
    with zipfile.ZipFile(path) as zf:
        index = json.loads(zf.read("modrinth.index.json"))
        if index.get("game") != "minecraft" or index.get("formatVersion") != 1:
            raise PackError("Unsupported .mrpack (expected formatVersion 1 for minecraft)")

        deps = index.get("dependencies", {})
        mc = deps.get("minecraft")
        if not mc:
            raise PackError(".mrpack has no minecraft version")
        loader = next((k for k in LOADER_KEYS if k in deps), "")
        name = index.get("name") or Path(path).stem
        log(f"📦 {name} {index.get('versionId', '')}".rstrip())
        log(f"  Minecraft {mc}" + (f", {loader} {deps[loader]}" if loader else " (vanilla)"))

        vid = ensure_loader(home, mc, loader, deps.get(loader, ""), runtime, image, workdir, log)

        # Each pack gets its own game dir, so its mods never mix with others.
        game_dir = Path(home) / "versions" / vid
        game_dir.mkdir(parents=True, exist_ok=True)
        result = ImportResult("mrpack", name, vid, game_dir)

        manifest_file = game_dir / MANIFEST_NAME
        old = []
        if manifest_file.is_file():
            try:
                old = json.loads(manifest_file.read_text()).get("files", [])
            except ValueError:
                old = []

        installed: List[str] = []
        files = [
            f for f in index.get("files", []) if (f.get("env") or {}).get("client") != "unsupported"
        ]
        for i, f in enumerate(files, 1):
            target = safe_join(game_dir, f["path"])
            rel = target.relative_to(game_dir.resolve()).as_posix()
            installed.append(rel)
            if _file_matches(target, f.get("hashes", {})):
                log(f"  [{i}/{len(files)}] {target.name} (up to date)")
                continue
            log(f"  [{i}/{len(files)}] {target.name}")
            errors = []
            for url in f.get("downloads", []):
                try:
                    download(url, target, hashes=f.get("hashes"), size=f.get("fileSize"))
                    break
                except PackError as e:
                    errors.append(str(e))
            else:
                raise PackError(f"Could not download {target.name}: {'; '.join(errors)}")

        for prefix in ("overrides/", "client-overrides/"):
            installed += _extract_prefix(zf, prefix, game_dir, log)

    # Drop files a previous version of this pack installed but this one doesn't.
    for rel in set(old) - set(installed):
        try:
            stale = safe_join(game_dir, rel)
            if stale.is_file():
                stale.unlink()
                log(f"  - removed {rel} (no longer in the pack)")
        except PackError:
            continue
    manifest_file.write_text(json.dumps({"name": name, "files": sorted(set(installed))}, indent=1))

    # Pre-added servers: also offer them in the shared folder if it has none yet.
    servers = game_dir / "servers.dat"
    shared_servers = Path(home) / "servers.dat"
    if servers.is_file() and not shared_servers.exists():
        shutil.copyfile(servers, shared_servers)

    result.files = len(installed)
    upsert_profile(home, name, vid, game_dir)
    result.notes.append(f"Profile '{name}' uses version {vid}")
    return result


def import_mcprofile(path: Path, home: Path, log: Log = _nolog) -> ImportResult:
    with zipfile.ZipFile(path) as zf:
        meta = json.loads(zf.read("profile_metadata.json"))
        profile = meta.get("profile_data", {}) or {}
        vid = _safe_name(meta.get("version_id") or profile.get("lastVersionId") or "")
        if not vid:
            raise PackError("Profile archive has no version id")
        name = profile.get("name") or vid
        log(f"📥 Profile {name} ({vid})")

        version_dir = Path(home) / "versions" / vid
        version_dir.mkdir(parents=True, exist_ok=True)
        written = _extract_prefix(zf, "version/", version_dir, log)
        game = _extract_prefix(zf, "gamedata/", version_dir, log)

    upsert_profile(home, name, vid, version_dir if (game or profile.get("gameDir")) else None)
    return ImportResult("mcprofile", name, vid, version_dir, len(written) + len(game))


def _mods_zip_layout(names: List[str]) -> Dict[str, str]:
    """Map archive members to game-dir-relative paths for a plain mods zip."""
    files = [n for n in names if not n.endswith("/")]
    # Strip one wrapper folder ("MyPack/mods/x.jar") if everything sits inside it.
    tops = {n.split("/", 1)[0] for n in files if "/" in n}
    wrapper = ""
    if len(tops) == 1 and all("/" in n for n in files):
        top = tops.pop()
        if top.lower() not in GAME_SUBDIRS:
            wrapper = top + "/"
    mapping = {}
    for n in files:
        rel = n[len(wrapper) :] if wrapper and n.startswith(wrapper) else n
        first = rel.split("/", 1)[0].lower()
        if "/" in rel and first in GAME_SUBDIRS:
            mapping[n] = rel
        elif rel.lower().endswith(".jar"):
            mapping[n] = "mods/" + rel.rsplit("/", 1)[-1]
    return mapping


def import_mods_zip(
    path: Path, home: Path, target_version: Optional[str] = None, log: Log = _nolog
) -> ImportResult:
    """Install a plain zip of mods into a version's folder, or the shared .minecraft."""
    if target_version:
        target_version = _safe_name(target_version)
        root = Path(home) / "versions" / target_version
        if not root.is_dir():
            raise PackError(f"Version {target_version} is not installed")
    else:
        root = Path(home)
    with zipfile.ZipFile(path) as zf:
        mapping = _mods_zip_layout(zf.namelist())
        if not mapping:
            raise PackError("No mods found in the archive")
        where = target_version or "shared mods folder"
        log(
            f"📥 Installing {sum(v.startswith('mods/') for v in mapping.values())} mod(s) into {where}"
        )
        for member, rel in mapping.items():
            info = zf.getinfo(member)
            if _is_symlink(info):
                continue
            _write_member(zf, info, safe_join(root, rel))
            log(f"  + {rel}")
    if target_version:
        # Point the version's profile at its own folder so the mods are picked up.
        upsert_profile(home, target_version, target_version, root)
    return ImportResult("mods", Path(path).name, target_version or "", root, len(mapping))


def import_archive(
    source: str,
    home: Path = HOME_DIR,
    runtime: str = "podman",
    image: str = "tlauncher-java:21",
    log: Log = _nolog,
    choose_target: Optional[Callable[[List[str]], Optional[str]]] = None,
    target_version: Optional[str] = None,
) -> ImportResult:
    """
    Import a file path or URL of any supported kind.

    choose_target(versions) is called for plain mod zips when target_version is
    not given; return a version id, "" for the shared folder, or None to cancel.
    """
    home = Path(home)
    with tempfile.TemporaryDirectory(prefix="tl-import-") as tmp:
        path = fetch_source(source, Path(tmp), log)
        kind = detect_kind(path)
        if kind == "mrpack":
            return import_mrpack(path, home, runtime, image, Path(tmp), log)
        if kind == "mcprofile":
            return import_mcprofile(path, home, log)
        if target_version is None and choose_target is not None:
            target_version = choose_target(list_modded_versions(home))
            if target_version is None:
                raise PackError("Import cancelled")
        return import_mods_zip(path, home, target_version or None, log)


# ── Export ───────────────────────────────────────────────────────────────────


def export_profile(
    profile_id: str, out_path: Path, home: Path = HOME_DIR, log: Log = _nolog
) -> Path:
    """
    Write a .mcprofile.zip: metadata, the version folder, and the profile's mods,
    configs etc. Profiles without their own game folder get the shared mods/ and
    config/ included, so the mods always travel with the profile.
    """
    home = Path(home)
    data = _load_profiles(home)
    profile = data.get("profiles", {}).get(profile_id)
    if profile is None:
        raise PackError(f"Profile '{profile_id}' not found")
    vid = profile.get("lastVersionId", "unknown")
    version_dir = home / "versions" / _safe_name(vid)

    game_dir = host_path(home, profile.get("gameDir", ""))
    sources = []  # (host dir, archive prefix)
    if version_dir.is_dir():
        sources.append((version_dir, "version/"))
    if game_dir is None or game_dir.resolve() == home.resolve():
        for sub in ("mods", "config"):
            if (home / sub).is_dir():
                sources.append((home / sub, f"gamedata/{sub}/"))
    elif game_dir.resolve() != version_dir.resolve() and game_dir.is_dir():
        sources.append((game_dir, "gamedata/"))

    out_path = Path(out_path)
    count = 0
    with zipfile.ZipFile(out_path, "w", zipfile.ZIP_DEFLATED) as zf:
        meta = {
            "profile_id": profile_id,
            "profile_data": profile,
            "version_id": vid,
            "export_version": "1.1",
        }
        zf.writestr("profile_metadata.json", json.dumps(meta, indent=2))
        for src, prefix in sources:
            for f in sorted(src.rglob("*")):
                if f.is_file() and not f.is_symlink():
                    arc = prefix + f.relative_to(src).as_posix()
                    zf.write(f, arc)
                    count += 1
        log(f"  {count} file(s) written")
    return out_path
