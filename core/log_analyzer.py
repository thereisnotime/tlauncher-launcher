"""Pattern-based log analysis with fix recommendations."""

import re
from dataclasses import dataclass
from typing import List


@dataclass
class LogFinding:
    level: str  # "error" or "warning"
    title: str
    detail: str
    recommendation: str


# (compiled_regex, level, title, detail, recommendation)
_PATTERNS = [
    # Image / registry
    (
        re.compile(r"denied: requested access to the resource is denied", re.I),
        "error",
        "Image not found in registry",
        "The container image 'tlauncher-java' has not been built locally.",
        "Build it first:  make build-podman\n"
        "  or:  podman build -f Containerfile -t tlauncher-java .",
    ),
    (
        re.compile(r"(no such image|image not known)", re.I),
        "error",
        "Container image missing",
        "The 'tlauncher-java' image does not exist locally.",
        "Build it first:  make build-podman",
    ),
    # NVIDIA / GPU
    (
        re.compile(r"ldcache error", re.I),
        "error",
        "NVIDIA ldcache error",
        "NVIDIA container toolkit reported an ldcache failure.",
        "Run:  sudo nvidia-ctk runtime configure --runtime=podman\n"
        "Then start again.",
    ),
    (
        re.compile(r"nvidia-container-cli.*error", re.I),
        "error",
        "NVIDIA container CLI error",
        "The NVIDIA container runtime failed to initialize.",
        "Run:  sudo nvidia-ctk runtime configure --runtime=podman\n"
        "If it persists:  sudo nvidia-ctk config --set nvidia-container-runtime.mode=csv",
    ),
    (
        re.compile(r"Failed to initialize NVML", re.I),
        "error",
        "NVIDIA driver not loaded",
        "NVML could not connect to the NVIDIA driver.",
        "Run:  sudo modprobe nvidia\n"
        "If that fails, reinstall your NVIDIA drivers.",
    ),
    # X11 / display
    (
        re.compile(r"(cannot connect to X server|No protocol specified)", re.I),
        "error",
        "X11 access denied",
        "The container cannot connect to your X display.",
        "Run:  xhost +SI:localuser:$USER\n"
        "Or enable auto_xhost in your config.",
    ),
    (
        re.compile(r"(DISPLAY is not set|Can't open display|failed to open display)", re.I),
        "error",
        "Display variable missing",
        "No DISPLAY environment variable is set.",
        "Ensure DISPLAY is exported:  export DISPLAY=:0",
    ),
    (
        re.compile(r"(GLXBadFBConfig|libGL error)", re.I),
        "warning",
        "OpenGL/GLX configuration issue",
        "OpenGL initialization reported errors — may cause rendering problems.",
        "Check host GPU drivers match the container's expectations:\n"
        "  glxinfo | grep 'OpenGL version'",
    ),
    # Java / JVM
    (
        re.compile(r"java\.lang\.OutOfMemoryError", re.I),
        "error",
        "Java out of memory",
        "The JVM ran out of heap space.",
        "Increase mem_limit in compose.base.yaml (currently 8g).\n"
        "Also check -Xmx in your JVM args inside TLauncher.",
    ),
    (
        re.compile(r"(Segmentation fault|SIGSEGV)", re.I),
        "error",
        "JVM crash (segfault)",
        "The Java process crashed with a segmentation fault.",
        "Often a GPU driver or OpenGL issue.\n"
        "Try switching GPU mode to 'none' to isolate the problem.",
    ),
    (
        re.compile(r"java\.lang\.UnsatisfiedLinkError", re.I),
        "error",
        "Missing native library",
        "Java could not load a required native library.",
        "The container may be missing a system library.\n"
        "Try rebuilding:  make build-podman",
    ),
    # Network / auth
    (
        re.compile(r"(Authentication servers are down|Invalid session|Failed to authenticate)", re.I),
        "warning",
        "Authentication issue",
        "Mojang/Microsoft auth servers could not be reached.",
        "Check https://status.minecraft.net — if servers are up, re-login in TLauncher.",
    ),
    (
        re.compile(r"(Failed to download|download failed|Unable to download)", re.I),
        "warning",
        "Download failure",
        "A required file could not be downloaded.",
        "Check your internet connection. If using a VPN, try disabling it.",
    ),
    # Audio
    (
        re.compile(r"(pa_context_connect.*failed|PulseAudio.*failed|pulse.*connection refused)", re.I),
        "warning",
        "PulseAudio connection failed",
        "The container could not connect to the PulseAudio server.",
        "Check PulseAudio is running:  pulseaudio --check -v\n"
        "Or switch audio to 'none' in your config.",
    ),
    # Disk / permissions
    (
        re.compile(r"no space left on device", re.I),
        "error",
        "Disk full",
        "The host filesystem has no space remaining.",
        "Free up disk space:  df -h",
    ),
    (
        re.compile(r"read-only file system", re.I),
        "error",
        "Read-only filesystem error",
        "A write was attempted on a path not included in the writable mounts.",
        "Check tmpfs and volume mounts in compose.base.yaml cover all paths the app writes to.",
    ),
    (
        re.compile(r"permission denied", re.I),
        "warning",
        "Permission denied",
        "A file or resource was inaccessible due to permissions.",
        "Check ownership of ./home, ./launcher, and ./tlauncher-data:\n"
        "  ls -la  (in the Minecraft directory)",
    ),
]


def analyze_lines(lines: List[str]) -> List[LogFinding]:
    """Scan log lines for known error patterns. Returns deduplicated findings."""
    findings: List[LogFinding] = []
    seen: set = set()

    for line in lines:
        for pattern, level, title, detail, recommendation in _PATTERNS:
            if title in seen:
                continue
            if pattern.search(line):
                findings.append(
                    LogFinding(level=level, title=title, detail=detail, recommendation=recommendation)
                )
                seen.add(title)

    return findings
