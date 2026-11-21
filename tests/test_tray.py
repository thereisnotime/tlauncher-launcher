import socket
import subprocess
import time

import pytest

from core import tray


@pytest.fixture
def sock_path(tmp_path):
    # AF_UNIX paths are limited to ~107 bytes; pytest tmp paths can be long.
    import tempfile
    from pathlib import Path

    d = Path(tempfile.mkdtemp(prefix="tl-"))
    yield d / "launcher.sock"
    for p in d.iterdir():
        p.unlink()
    d.rmdir()


def test_backend_name():
    class FakeIcon:
        pass

    FakeIcon.__module__ = "pystray._appindicator"
    assert tray.backend_name(FakeIcon()) == "appindicator"
    FakeIcon.__module__ = "pystray._xorg"
    assert tray.backend_name(FakeIcon()) == "xorg"


@pytest.mark.parametrize(
    ("backend", "sni", "expected"),
    [
        ("appindicator", True, True),
        ("appindicator", None, True),  # unknown: trust it
        ("appindicator", False, False),  # GNOME without the extension
        ("xorg", False, True),
        ("gtk", None, True),
    ],
)
def test_can_hide_to_tray(backend, sni, expected):
    assert tray.can_hide_to_tray(backend, sni) is expected


def test_sni_host_gdbus(monkeypatch):
    monkeypatch.setenv("DBUS_SESSION_BUS_ADDRESS", "unix:path=/x")
    monkeypatch.setattr(tray.shutil, "which", lambda n: "/usr/bin/gdbus" if n == "gdbus" else None)

    def run(out, rc=0):
        return lambda *a, **k: subprocess.CompletedProcess(a, rc, stdout=out, stderr="")

    monkeypatch.setattr(tray.subprocess, "run", run("(true,)\n"))
    assert tray.sni_host_available() is True
    monkeypatch.setattr(tray.subprocess, "run", run("(false,)\n"))
    assert tray.sni_host_available() is False
    monkeypatch.setattr(tray.subprocess, "run", run("", rc=1))
    assert tray.sni_host_available() is None


def test_sni_host_unknown_without_tools(monkeypatch):
    monkeypatch.setenv("DBUS_SESSION_BUS_ADDRESS", "unix:path=/x")
    monkeypatch.setattr(tray.shutil, "which", lambda n: None)
    assert tray.sni_host_available() is None


def test_notify_without_instance(sock_path):
    assert tray.notify_running_instance(sock_path) is False


def test_instance_server_round_trip(sock_path):
    shown = []
    server = tray.InstanceServer(lambda: shown.append(1), path=sock_path)
    assert server.start()
    try:
        assert sock_path.stat().st_mode & 0o777 == 0o600
        assert tray.notify_running_instance(sock_path) is True
        assert shown == [1]
        # A second server must not steal the socket from the live one.
        assert tray.InstanceServer(lambda: None, path=sock_path).start() is False
        assert tray.notify_running_instance(sock_path) is True
        assert shown == [1, 1]
    finally:
        server.close()
    assert not sock_path.exists()
    assert tray.notify_running_instance(sock_path) is False


def test_instance_server_replaces_stale_socket(sock_path):
    stale = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    stale.bind(str(sock_path))
    stale.close()  # file left behind, nobody listening (crashed run)
    assert sock_path.exists()
    assert tray.notify_running_instance(sock_path) is False
    server = tray.InstanceServer(lambda: None, path=sock_path)
    assert server.start()
    try:
        assert tray.notify_running_instance(sock_path) is True
    finally:
        server.close()


def test_instance_server_ignores_garbage(sock_path):
    shown = []
    server = tray.InstanceServer(lambda: shown.append(1), path=sock_path)
    assert server.start()
    try:
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as s:
            s.connect(str(sock_path))
            s.sendall(b"rm -rf\n")
            s.settimeout(1)
            assert s.recv(16) == b""
        time.sleep(0.05)
        assert shown == []
        assert tray.notify_running_instance(sock_path) is True
    finally:
        server.close()


def test_pystray_available_reports_missing(monkeypatch):
    import builtins

    real_import = builtins.__import__

    def fake(name, *a, **k):
        if name == "pystray":
            raise ImportError("No module named 'pystray'")
        return real_import(name, *a, **k)

    monkeypatch.setattr(builtins, "__import__", fake)
    ok, why = tray.pystray_available()
    assert ok is False
    assert "pystray" in why or "PIL" in why


class _FakeWindow:
    def __init__(self):
        self.calls = []

    def withdraw(self):
        self.calls.append("withdraw")

    def destroy(self):
        self.calls.append("destroy")


def _fake_gui(icon, hide_ok):
    from ui.tray import TrayMixin

    gui = TrayMixin.__new__(TrayMixin)
    gui.window = _FakeWindow()
    gui._tray_icon = icon
    gui._tray_hide_ok = hide_ok
    gui._tray_hint_shown = False
    gui._window_hidden = False
    gui.logged = []
    gui.log = gui.logged.append
    return gui


class _FakeIcon:
    stopped = False

    def stop(self):
        self.stopped = True


def test_close_hides_when_tray_visible():
    gui = _fake_gui(_FakeIcon(), hide_ok=True)
    gui._on_window_close()
    gui._on_window_close()
    assert gui.window.calls == ["withdraw", "withdraw"]
    assert gui._window_hidden is True  # polls slow down while hidden
    assert len(gui.logged) == 1  # the hint is shown once


@pytest.mark.parametrize(("icon", "hide_ok"), [(None, False), (_FakeIcon(), False)])
def test_close_quits_without_visible_tray(icon, hide_ok):
    gui = _fake_gui(icon, hide_ok)
    gui._on_window_close()
    assert gui.window.calls == ["destroy"]
    assert gui._tray_icon is None
    if icon is not None:
        assert icon.stopped


def test_signal_calls_off_main_thread_are_ignored():
    import signal
    import threading

    tray.allow_signal_calls_off_main_thread()
    tray.allow_signal_calls_off_main_thread()  # idempotent
    before = signal.getsignal(signal.SIGINT)
    errors = []

    def worker():
        try:
            signal.signal(signal.SIGINT, signal.SIG_DFL)  # what pystray's gtk backend does
        except Exception as e:
            errors.append(e)

    t = threading.Thread(target=worker)
    t.start()
    t.join()
    assert errors == []
    assert signal.getsignal(signal.SIGINT) == before  # untouched
    # The main thread still really sets handlers.
    old = signal.signal(signal.SIGUSR1, signal.SIG_IGN)
    assert signal.getsignal(signal.SIGUSR1) == signal.SIG_IGN
    signal.signal(signal.SIGUSR1, old)


class _AfterWindow:
    def __init__(self):
        self.scheduled = []

    def after(self, ms, fn, *args):
        self.scheduled.append(ms)
        return f"job{len(self.scheduled)}"


@pytest.mark.parametrize(("hidden", "expected"), [(False, 2000), (True, 15000)])
def test_state_poll_slows_down_when_hidden(hidden, expected):
    from ui.state import ContainerStateMixin

    gui = ContainerStateMixin.__new__(ContainerStateMixin)
    gui.window = _AfterWindow()
    gui._window_hidden = hidden
    gui._last_running = None
    gui._state_worker_busy = True  # don't start a real podman check
    gui._sync_control_buttons = lambda running: None
    gui._tray_sync_state = lambda running: None
    gui._schedule_state_poll()
    assert gui.window.scheduled == [expected]


def test_service_poll_pauses_when_hidden():
    from ui.state import ContainerStateMixin

    gui = ContainerStateMixin.__new__(ContainerStateMixin)
    gui.window = _AfterWindow()
    gui._window_hidden = True
    gui._svc_worker_busy = False
    gui._schedule_service_poll()
    assert gui.window.scheduled == [15000]
    assert gui._svc_worker_busy is False  # no podman/docker check was started
