import pytest

from core import log_analyzer
from core.log_analyzer import analyze_lines

SAMPLES = [
    (
        "failed to connect to the docker API at unix:///run/user/1000/podman/podman.sock; "
        "check if the path is correct",
        "docker-compose can't reach podman's API socket",
    ),
    (
        "Error: denied: requested access to the resource is denied",
        "Image not found in registry",
    ),
    ("Error: tlauncher-java:21: image not known", "Container image missing"),
    ("Error response from daemon: No such image: tlauncher-java:21", "Container image missing"),
    ("nvidia-container-cli: ldcache error: open failed", "NVIDIA ldcache error"),
    ("nvidia-container-cli: initialization error: driver rpc error", "NVIDIA container CLI error"),
    ("Failed to initialize NVML: Driver/library version mismatch", "NVIDIA driver not loaded"),
    ("Error: cannot connect to X server :0", "X11 access denied"),
    ("No protocol specified", "X11 access denied"),
    ("java.awt.AWTError: Can't open display: :1", "Display variable missing"),
    ("Exception: DISPLAY is not set", "Display variable missing"),
    ("libGL error: failed to load driver: iris", "OpenGL/GLX configuration issue"),
    ("X Error: GLXBadFBConfig", "OpenGL/GLX configuration issue"),
    ("Exception in thread main java.lang.OutOfMemoryError: Java heap space", "Java out of memory"),
    ("# SIGSEGV (0xb) at pc=0x00007f", "JVM crash (segfault)"),
    ("entrypoint.sh: line 40: 12 Segmentation fault (core dumped)", "JVM crash (segfault)"),
    ("java.lang.UnsatisfiedLinkError: no lwjgl in java.library.path", "Missing native library"),
    ("[Auth] Failed to authenticate: Invalid session", "Authentication issue"),
    ("Failed to download https://libraries.minecraft.net/x.jar", "Download failure"),
    ("pa_context_connect() failed: Connection refused", "PulseAudio connection failed"),
    ("write /home/app/x: no space left on device", "Disk full"),
    ("open /etc/foo: read-only file system", "Read-only filesystem error"),
    ("open /home/app/.minecraft/options.txt: Permission denied", "Permission denied"),
]


@pytest.mark.parametrize(("line", "title"), SAMPLES)
def test_pattern_matches(line, title):
    titles = [f.title for f in analyze_lines([line])]
    assert title in titles


def test_samples_cover_every_pattern():
    all_titles = {p[2] for p in log_analyzer._PATTERNS}
    assert {title for _line, title in SAMPLES} == all_titles


def test_finding_fields():
    (finding,) = analyze_lines(["java.lang.OutOfMemoryError"])
    assert finding.level == "error"
    assert finding.detail
    assert finding.recommendation


def test_duplicates_collapsed_and_order_follows_log():
    lines = [
        "Failed to download a.jar",
        "java.lang.OutOfMemoryError",
        "Failed to download b.jar",
        "java.lang.OutOfMemoryError again",
    ]
    assert [f.title for f in analyze_lines(lines)] == ["Download failure", "Java out of memory"]


def test_clean_log_has_no_findings():
    lines = ["[Loading] SUCCESS", "Started!", "Setting user: Steve", ""]
    assert analyze_lines(lines) == []
