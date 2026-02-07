# TLauncher Containerized Setup

Run Minecraft via TLauncher in a containerized environment with full GPU acceleration and audio support.

## Quick Start

**1. Build the image:**

```bash
podman build -t tlauncher-java .
```

**2. Choose your configuration and run:**

```bash
# Podman + NVIDIA + X11 + Audio (most common)
xhost +SI:localuser:$USER
podman compose -f compose.base.yaml -f compose.podman.yaml -f compose.nvidia.yaml -f compose.x11.yaml -f compose.audio-pulseaudio.yaml up

# Docker + AMD + Wayland + Audio
docker compose -f compose.base.yaml -f compose.docker.yaml -f compose.amd.yaml -f compose.wayland.yaml -f compose.audio-pulseaudio.yaml up
```

## Configuration Files

The setup uses modular compose files that are combined to match your system:

### Base Configuration

- **`compose.base.yaml`** - Core container config (always required)

### Container Runtime

- **`compose.podman.yaml`** - Podman rootless mode
- **`compose.docker.yaml`** - Docker compatibility

### GPU Support

- **`compose.nvidia.yaml`** - NVIDIA GPUs (RTX, GTX, etc.)
- **`compose.amd.yaml`** - AMD or Intel GPUs

### Display Server

- **`compose.x11.yaml`** - X11 (most Linux distros)
- **`compose.wayland.yaml`** - Wayland (GNOME, newer systems)

### Audio

- **`compose.audio-pulseaudio.yaml`** - PulseAudio/PipeWire (Linux)
- **`compose.audio-none.yaml`** - No audio (Windows/servers)

## Common Configurations

### Linux - Podman + NVIDIA + X11

```bash
xhost +SI:localuser:$USER
podman compose \
  -f compose.base.yaml \
  -f compose.podman.yaml \
  -f compose.nvidia.yaml \
  -f compose.x11.yaml \
  -f compose.audio-pulseaudio.yaml \
  up
```

### Linux - Podman + AMD + Wayland

```bash
podman compose \
  -f compose.base.yaml \
  -f compose.podman.yaml \
  -f compose.amd.yaml \
  -f compose.wayland.yaml \
  -f compose.audio-pulseaudio.yaml \
  up
```

### Linux - Docker + NVIDIA + X11

```bash
xhost +SI:localuser:$USER
docker compose \
  -f compose.base.yaml \
  -f compose.docker.yaml \
  -f compose.nvidia.yaml \
  -f compose.x11.yaml \
  -f compose.audio-pulseaudio.yaml \
  up
```

### Windows (WSL2) - Docker + NVIDIA + No Audio

```bash
docker compose \
  -f compose.base.yaml \
  -f compose.docker.yaml \
  -f compose.nvidia.yaml \
  -f compose.x11.yaml \
  -f compose.audio-none.yaml \
  up
```

## Verify Your System

### Check GPU type

```bash
# NVIDIA
nvidia-smi

# AMD/Intel
lspci | grep -i vga
```

### Check display server

```bash
echo $XDG_SESSION_TYPE
# Output: x11 or wayland
```

### Check audio system

```bash
pactl info | grep "Server Name"
# Output: PulseAudio or PipeWire
```

## Background Mode

Add `-d` flag to run detached:

```bash
podman compose -f compose.base.yaml -f compose.podman.yaml ... up -d
```

Stop with:

```bash
podman compose -f compose.base.yaml -f compose.podman.yaml ... down
```

## Shell Aliases (Recommended)

Add to your `~/.bashrc` or `~/.zshrc`:

```bash
# Podman + NVIDIA + X11 + Audio
alias minecraft='xhost +SI:localuser:$USER && podman compose -f compose.base.yaml -f compose.podman.yaml -f compose.nvidia.yaml -f compose.x11.yaml -f compose.audio-pulseaudio.yaml'

# Then just run:
minecraft up
minecraft down
minecraft logs -f
```

## Troubleshooting

### No display

- X11: Run `xhost +SI:localuser:$USER` first
- Check `echo $DISPLAY` is set
- Verify `/tmp/.X11-unix` exists

### No GPU acceleration

- NVIDIA: Run `nvidia-smi` to verify drivers
- AMD: Check `/dev/dri` exists
- Monitor with `watch -n 1 nvidia-smi`

### No audio

- Linux: Verify PulseAudio/PipeWire running with `pactl info`
- Check `/run/user/1000/pulse/native` socket exists
- Use `compose.audio-none.yaml` if audio not needed

### Permission denied

- Podman: Ensure rootless mode is configured
- Check file ownership: `ls -la launcher/ home/ tlauncher-data/`

## File Structure

```text
.
├── compose.base.yaml              # Base configuration
├── compose.podman.yaml            # Podman-specific
├── compose.docker.yaml            # Docker-specific
├── compose.nvidia.yaml            # NVIDIA GPU
├── compose.amd.yaml               # AMD/Intel GPU
├── compose.x11.yaml               # X11 display
├── compose.wayland.yaml           # Wayland display
├── compose.audio-pulseaudio.yaml  # Audio (Linux)
├── compose.audio-none.yaml        # No audio
├── Containerfile                  # Image definition
├── entrypoint.sh                  # Startup script
├── launcher/                      # TLauncher app
├── home/                          # Minecraft data (saves, mods, etc.)
└── tlauncher-data/                # TLauncher cache/logs
```

See **[STRUCTURE.md](STRUCTURE.md)** for details on Minecraft file organization.

See **[manual-runbook.md](manual-runbook.md)** for the original step-by-step manual.

## Windows Support

### WSL2 + Docker Desktop

1. Install WSL2 with Ubuntu
2. Install Docker Desktop with WSL2 backend
3. Use X server (VcXsrv or Xming) for display
4. Audio support is experimental/limited

```bash
# In WSL2
export DISPLAY=$(cat /etc/resolv.conf | grep nameserver | awk '{print $2}'):0

docker compose \
  -f compose.base.yaml \
  -f compose.docker.yaml \
  -f compose.nvidia.yaml \
  -f compose.x11.yaml \
  -f compose.audio-none.yaml \
  up
```

## Advanced

### Custom Java arguments

Edit `home/TlauncherProfiles.json` and modify `javaArgs` for your profile.

### Resource limits

Edit `compose.base.yaml`:

- `mem_limit: 8g` - Maximum RAM
- `pids_limit: 512` - Process limit

### Backup worlds

```bash
tar -czf minecraft-backup-$(date +%Y%m%d).tar.gz ./home/saves/
```
