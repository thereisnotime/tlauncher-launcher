"""
Minecraft's own heap size (-Xmx), as stored in TLauncher's settings.

TLauncher keeps it in tlauncher-data/tlauncher-2.0.properties under
`minecraft.memory.ram3` (MB). It has to stay below the container's memory cap
(TLAUNCHER_MEM_LIMIT), with headroom for the JVM itself and TLauncher, or the
kernel kills the game when the heap fills up.
"""

import re
from pathlib import Path

PROPERTIES = Path(__file__).resolve().parent.parent / "tlauncher-data" / "tlauncher-2.0.properties"
RAM_KEY = "minecraft.memory.ram3"
HEADROOM_MB = 1536  # JVM overhead + TLauncher's own window
MODPACK_RAM_MB = 4096
BIG_MODPACK_RAM_MB = 6144
BIG_MODPACK_MODS = 80


def mem_limit_mb(memory: str) -> int:
    """'8g' -> 8192, '512m' -> 512."""
    m = re.fullmatch(r"\s*(\d+)\s*([gGmM]?)\s*", str(memory or ""))
    if not m:
        return 8192
    value = int(m.group(1))
    return value if m.group(2).lower() == "m" else value * 1024


def max_game_ram(cap_mb: int) -> int:
    return max(1024, cap_mb - HEADROOM_MB)


def get_game_ram(props: Path = PROPERTIES) -> int | None:
    """Current game RAM in MB, or None if TLauncher hasn't written its settings yet."""
    try:
        for line in Path(props).read_text(encoding="utf-8", errors="replace").splitlines():
            key, sep, value = line.partition("=")
            if sep and key.strip() == RAM_KEY and value.strip().isdigit():
                return int(value.strip())
    except OSError:
        return None
    return None


def set_game_ram(mb: int, props: Path = PROPERTIES) -> None:
    """
    Write the game RAM. TLauncher rewrites this file when it exits, so only
    call this while it isn't running.
    """
    props = Path(props)
    lines = props.read_text(encoding="utf-8").splitlines() if props.exists() else []
    out, found = [], False
    for line in lines:
        if line.partition("=")[0].strip() == RAM_KEY:
            out.append(f"{RAM_KEY}={int(mb)}")
            found = True
        else:
            out.append(line)
    if not found:
        out.append(f"{RAM_KEY}={int(mb)}")
    props.parent.mkdir(parents=True, exist_ok=True)
    tmp = props.with_suffix(".properties.tmp")
    tmp.write_text("\n".join(out) + "\n", encoding="utf-8")
    tmp.replace(props)


def recommended_game_ram(cap_mb: int, mod_count: int = 0) -> int:
    """Sensible heap for a modpack, capped to what fits in the container."""
    want = BIG_MODPACK_RAM_MB if mod_count >= BIG_MODPACK_MODS else MODPACK_RAM_MB
    return min(want, max_game_ram(cap_mb))


def suggest_for_modpack(current: int | None, cap_mb: int, mod_count: int) -> int | None:
    """New RAM to propose after a modpack import, or None if the current value is fine."""
    target = recommended_game_ram(cap_mb, mod_count)
    if current is None:
        return target
    if current > max_game_ram(cap_mb) or current < target:
        return target
    return None
