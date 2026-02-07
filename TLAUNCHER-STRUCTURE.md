# TLauncher Container Structure

This document explains how TLauncher organizes Minecraft files, mods, versions, and data within the containerized setup.

---

## Directory Overview

```
.
├── launcher/              # TLauncher application
│   └── TLauncher.jar     # Auto-downloaded on first run
├── home/                  # Minecraft game data (persistent)
│   ├── saves/            # Your worlds
│   ├── mods/             # Global mods (Forge/Fabric)
│   ├── resourcepacks/    # Texture packs
│   ├── shaderpacks/      # Shader packs (OptiFine/Iris)
│   ├── screenshots/      # In-game screenshots
│   ├── versions/         # Minecraft versions & mod loaders
│   ├── libraries/        # Game libraries
│   ├── assets/           # Game assets (sounds, textures)
│   └── runtime/          # Java runtimes per version
└── tlauncher-data/        # TLauncher cache & logs
    ├── cache/            # Downloaded files cache
    ├── logs/             # TLauncher logs
    └── starter/          # TLauncher updater data
```

---

## Minecraft Data (`./home/`)

Mounted to `/home/app/.minecraft` in container.

### Worlds & Saves

**Location:** `./home/saves/`

Each world is a separate directory:
```
saves/
├── World1/               # Singleplayer world
│   ├── level.dat         # World metadata
│   ├── region/           # Chunk data
│   ├── playerdata/       # Player stats
│   └── data/             # Map data, structures
└── MyServer/             # Multiplayer world
```

**Backup:** `cp -r ./home/saves/World1 ./backups/`

### Mods

**Location:** `./home/mods/`

- For **Forge/Fabric** modded versions only
- Place `.jar` files directly in this directory
- Version-specific: mods must match Minecraft version

**Example:**
```
mods/
├── OptiFine_1.20.1.jar
├── JourneyMap-1.20.1.jar
└── JEI-1.20.1.jar
```

**Note:** Vanilla Minecraft ignores this folder.

### Resource Packs (Textures)

**Location:** `./home/resourcepacks/`

- `.zip` files containing custom textures/models
- Activated in-game: Options → Resource Packs

### Shader Packs

**Location:** `./home/shaderpacks/`

- Requires **OptiFine** or **Iris** mod
- `.zip` files with lighting/shadow effects
- Activated in-game: Options → Video Settings → Shaders

### Screenshots

**Location:** `./home/screenshots/`

- Press `F2` in-game to capture
- PNG format with timestamp

---

## Minecraft Versions (`./home/versions/`)

TLauncher downloads and stores each Minecraft version separately.

### Version Structure

```
versions/
├── 1.21.1/                    # Vanilla 1.21.1
│   ├── 1.21.1.jar            # Game JAR
│   ├── 1.21.1.json           # Version metadata
│   └── natives/              # Native libraries (LWJGL)
├── 1.20.1-forge-47.2.0/      # Forge modded
│   ├── 1.20.1-forge-47.2.0.jar
│   ├── 1.20.1-forge-47.2.0.json
│   └── mods/                 # Version-specific mods
└── fabric-loader-1.20.1/     # Fabric modded
    ├── fabric-loader-1.20.1.jar
    └── fabric-loader-1.20.1.json
```

### Mod Loader Types

1. **Vanilla** - No mods, official Minecraft
2. **Forge** - Most popular mod loader
3. **Fabric** - Lightweight, modern mod loader
4. **OptiFine** - Performance & shaders (standalone or with Forge)
5. **Quilt** - Fabric fork with extra features

### Installing a Mod Loader

1. Open TLauncher
2. Click version dropdown
3. Select "Forge", "Fabric", or "OptiFine"
4. Choose Minecraft version
5. Click "Install"

TLauncher downloads and installs automatically.

---

## TLauncher Data (`./tlauncher-data/`)

Mounted to `/home/app/.tlauncher` in container.

### Cache

**Location:** `./tlauncher-data/cache/`

- Downloaded configs, version manifests
- Skin/cape data
- Advertisement content
- Safe to delete (will re-download)

### Logs

**Location:** `./tlauncher-data/logs/`

```
logs/
├── tlauncher/              # Main launcher logs
│   └── tlauncher_*.log
└── starter/                # Updater logs
    └── starter_*.log
```

**View recent logs:**
```bash
tail -f ./tlauncher-data/logs/tlauncher/tlauncher_*.log
```

### Starter Data

**Location:** `./tlauncher-data/starter/`

- TLauncher updater cache
- Java runtime downloads
- Dependencies

---

## Version-Specific Mods

For **per-version mods** (instead of global), create a `mods/` folder inside the version directory:

```bash
# Example: Mods only for Forge 1.20.1
mkdir -p ./home/versions/1.20.1-forge-47.2.0/mods/
cp MyMod.jar ./home/versions/1.20.1-forge-47.2.0/mods/
```

**Global vs Version-Specific:**
- `./home/mods/` → All Forge/Fabric versions
- `./home/versions/X/mods/` → Only version X

---

## Profiles & Settings

**Location:** `./home/TlauncherProfiles.json`

Stores:
- Account configurations
- Version selections per profile
- JVM arguments
- Resolution settings

**Location:** `./home/options.txt`

In-game settings:
- Graphics options
- Keybinds
- Audio levels
- Resource packs enabled

---

## Java Runtimes

**Location:** `./home/runtime/`

TLauncher auto-downloads Java for each Minecraft version:

```
runtime/
├── java-runtime-alpha/     # Java 16 (MC 1.17)
├── java-runtime-beta/      # Java 17 (MC 1.18-1.20.4)
├── java-runtime-gamma/     # Java 21 (MC 1.20.5+)
└── jre-legacy/             # Java 8 (MC <1.17)
```

**Note:** These are separate from the container's OpenJDK 21, used only by Minecraft itself.

---

## Backup Strategy

### Essential Files

**Must backup:**
```bash
# Worlds (most important!)
./home/saves/

# Settings & profiles
./home/options.txt
./home/TlauncherProfiles.json

# Mods (if customized)
./home/mods/

# Resource packs (if custom/rare)
./home/resourcepacks/
```

**Can re-download:**
- `./home/versions/` - Minecraft versions
- `./home/libraries/` - Libraries
- `./home/assets/` - Game assets
- `./tlauncher-data/` - TLauncher cache

### Backup Command

```bash
# Backup worlds only (recommended)
tar -czf minecraft-backup-$(date +%Y%m%d).tar.gz ./home/saves/

# Full backup (large!)
tar -czf minecraft-full-backup-$(date +%Y%m%d).tar.gz ./home/
```

### Restore

```bash
# Restore worlds
tar -xzf minecraft-backup-20260207.tar.gz

# Or copy specific world
cp -r backup/World1 ./home/saves/
```

---

## Server Multiplayer

**Server list:** `./home/servers.dat` (binary format)

**Add server manually:** Use in-game "Add Server" menu.

**Reset server list:**
```bash
rm ./home/servers.dat
```

---

## Troubleshooting

### Corrupted World

```bash
# Backup first!
cp -r ./home/saves/World1 ./home/saves/World1.backup

# Try removing player data
rm -rf ./home/saves/World1/playerdata/
```

### Mod Conflicts

```bash
# Check TLauncher logs
tail -100 ./tlauncher-data/logs/tlauncher/tlauncher_*.log | grep -i error

# Remove all mods and add one by one
rm ./home/mods/*.jar
```

### Reset Minecraft (keep worlds)

```bash
# Remove everything except saves
cd ./home/
rm -rf assets libraries versions runtime mods resourcepacks
# Saves remain intact
```

### Fresh Start

```bash
# Nuclear option - delete everything
rm -rf ./home/* ./tlauncher-data/*
# Launcher will re-download everything
```

---

## Storage Usage

Typical sizes:
- Fresh install: ~500MB
- With 5-10 versions: ~2-5GB
- Large modpack: ~5-10GB
- Worlds: 50MB-5GB (depends on exploration)

**Check usage:**
```bash
du -sh ./home/
du -sh ./home/saves/
du -sh ./home/versions/
```

---

## Container Isolation Benefits

✅ **Isolated:** Minecraft doesn't touch your host system
✅ **Portable:** Copy `./home/` to new machine
✅ **Multiple instances:** Run different Minecraft setups (copy entire folder)
✅ **Safe updates:** TLauncher auto-updates won't break host
✅ **Clean uninstall:** Delete folder, done

---

## Quick Reference

| What | Where |
|------|-------|
| Worlds | `./home/saves/` |
| Mods | `./home/mods/` |
| Resource packs | `./home/resourcepacks/` |
| Screenshots | `./home/screenshots/` |
| Settings | `./home/options.txt` |
| Profiles | `./home/TlauncherProfiles.json` |
| Versions | `./home/versions/` |
| Logs | `./tlauncher-data/logs/tlauncher/` |

---

**Happy mining! ⛏️**
