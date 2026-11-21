# Manual Compose Runbook

Running the container by hand, without `./minecraft.py`. The launcher does exactly this
for you (plus detection, validation, modpack import and so on); `./minecraft.py doctor`
prints the command it would run on your machine.

## How the compose files fit together

One base file plus one overlay per choice, always in this order:

| Layer   | Files                                                        |
|---------|--------------------------------------------------------------|
| Base    | `compose.base.yaml`                                          |
| Runtime | `compose.podman.yaml` or `compose.docker.yaml`               |
| GPU     | `compose.nvidia.yaml`, `compose.amd.yaml`, `compose.intel.yaml` |
| Display | `compose.x11.yaml` or `compose.wayland.yaml` (via XWayland)  |
| Audio   | `compose.audio-pulseaudio.yaml` or `compose.audio-none.yaml` |

On Windows/WSL2, `compose.wslg.yaml` replaces the GPU, display and audio layers.

Environment variables the files read:

| Variable              | Default | Meaning                                          |
|-----------------------|---------|--------------------------------------------------|
| `TLAUNCHER_JAVA`      | `21`    | Image tag to run (`tlauncher-java:<java>`)       |
| `TLAUNCHER_MEM_LIMIT` | `8g`    | Container memory cap                             |
| `JAVA2D_PIPELINE`, `JAVAFX_PRISM`, `JAVA_UI_SCALE`, ... | | Launcher rendering tweaks, see the README |

Data lives next to the files: `./home` (Minecraft), `./tlauncher-data` (TLauncher settings
and logs) and `./launcher` (`TLauncher.jar`, downloaded on first start).

## Prerequisites

```bash
podman --version
podman compose version     # needs a provider, see below
```

`podman compose` needs a provider program. Prefer `podman-compose`
(`sudo dnf install podman-compose` / `sudo apt install podman-compose`). A `docker-compose`
binary also works, but only with podman's API socket running
(`systemctl --user enable --now podman.socket`). To pick one explicitly:

```bash
export PODMAN_COMPOSE_PROVIDER=/usr/bin/podman-compose
```

## Build the image (once per Java version)

```bash
podman build --build-arg JAVA_VERSION=21 -t tlauncher-java:21 .
# Java 25 instead:
podman build --build-arg JAVA_VERSION=25 -t tlauncher-java:25 . && export TLAUNCHER_JAVA=25
```

## Run (example: Podman + AMD + Wayland + audio)

```bash
FILES="-f compose.base.yaml -f compose.podman.yaml -f compose.amd.yaml \
       -f compose.wayland.yaml -f compose.audio-pulseaudio.yaml"

xhost +SI:localuser:$USER          # X11 and XWayland both need this, once per session
podman compose $FILES up           # foreground; add -d for background
podman compose $FILES logs -f      # follow logs (background mode)
podman compose $FILES down         # stop and remove the container
xhost -SI:localuser:$USER          # revoke access again (optional)
```

Swap the overlays for your setup, e.g. `compose.nvidia.yaml` and `compose.x11.yaml`.
Recreate the container after changing files or variables:

```bash
podman compose $FILES up --force-recreate
```

Check what the merged configuration looks like:

```bash
podman compose $FILES config
```

## Troubleshooting

### Window does not appear

```bash
echo "$XDG_SESSION_TYPE $DISPLAY"
ls /tmp/.X11-unix
xhost +SI:localuser:$USER
```

### `failed to connect to the docker API at unix:///run/user/.../podman.sock`

Podman used a `docker-compose` binary without its API socket running. Install
`podman-compose` or run `systemctl --user enable --now podman.socket`.

### GPU devices

```bash
ls -l /dev/dri          # AMD / Intel
ls -l /dev/nvidia*      # NVIDIA
watch -n 1 nvidia-smi   # the Java process should use GPU memory while playing
```

### Cleanup

```bash
podman image prune -f                 # dangling images from rebuilds
podman rmi tlauncher-java:latest      # pre-1.1 untagged image, no longer used
rm -rf ./home                         # resets ALL Minecraft data (worlds included)
```
