# TLauncher (JAR) – Podman Compose Runbook

**Files:**

- `compose.yaml` → X11
- `compose-wayland.yaml` → Wayland

**Assumptions:**

- Rootless Podman
- `TLauncher.jar` is in `./launcher/` directory
- Image name: `tlauncher-java`
- `./home` directory for Minecraft data (auto-created)
- `./tlauncher-data` directory for TLauncher cache/logs (auto-created)

---

## Prerequisites

```bash
podman --version
```

```bash
podman compose --version
```

```bash
test -f ./launcher/TLauncher.jar
```

---

## Build image (once)

```bash
podman build -t tlauncher-java .
```

---

## X11 Runbook (`compose.yaml`)

### Verify session type (X11 - optional)

```bash
echo "$XDG_SESSION_TYPE"
```

### Allow local user access to X server (per session)

```bash
xhost +SI:localuser:$USER
```

### Start TLauncher (X11 - foreground)

```bash
podman compose -f compose.yaml up
```

### Start TLauncher (X11 - background)

```bash
podman compose -f compose.yaml up -d
```

### View logs (X11)

```bash
podman compose -f compose.yaml logs -f
```

### Stop and remove container (X11)

```bash
podman compose -f compose.yaml down
```

### Revoke X server access (recommended)

```bash
xhost -SI:localuser:$USER
```

---

## Wayland Runbook (`compose-wayland.yaml`)

### Verify session type (Wayland)

```bash
echo "$XDG_SESSION_TYPE"
```

### Verify required Wayland variables

```bash
echo "WAYLAND_DISPLAY=$WAYLAND_DISPLAY"
echo "XDG_RUNTIME_DIR=$XDG_RUNTIME_DIR"
```

### Start TLauncher (Wayland - foreground)

```bash
podman compose -f compose-wayland.yaml up
```

### Start TLauncher (Wayland - background)

```bash
podman compose -f compose-wayland.yaml up -d
```

### View logs (Wayland)

```bash
podman compose -f compose-wayland.yaml logs -f
```

### Stop and remove container (Wayland)

```bash
podman compose -f compose-wayland.yaml down
```

---

## Common Operations

### Force recreate container (X11)

```bash
podman compose -f compose.yaml up --force-recreate
```

### Force recreate container (Wayland)

```bash
podman compose -f compose-wayland.yaml up --force-recreate
```

### Cleanup unused resources

```bash
podman system prune -f
```

---

## Troubleshooting

### X11: window does not appear

```bash
echo "$DISPLAY"
ls /tmp/.X11-unix
```

### Wayland: rendering issues

```bash
echo "$WAYLAND_DISPLAY"
```

### GPU device check (Intel / AMD)

```bash
ls -l /dev/dri
```

### GPU device check (NVIDIA)

```bash
ls -l /dev/nvidia*
```

### Monitor NVIDIA GPU usage

```bash
watch -n 1 nvidia-smi
```

**Look for the Java process using GPU memory when Minecraft is running.**

### Reset isolated application data

```bash
rm -rf ./home
```
