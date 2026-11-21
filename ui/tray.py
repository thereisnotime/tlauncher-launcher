"""Optional tray icon, close-to-tray, and the single-instance socket."""

from __future__ import annotations

import threading
import tkinter as tk
from typing import Any

from core.config import load_config, save_config
from core.tray import (
    INSTALL_HINT,
    InstanceServer,
    backend_name,
    can_hide_to_tray,
    pystray_available,
    sni_host_available,
)
from ui.base import GUIBase
from ui.common import APP_DIR


class TrayMixin(GUIBase):
    """Tray icon (pystray, optional). While it is shown, closing the window hides it."""

    def _init_tray(self) -> None:
        """Called once from __init__ after the config is loaded."""
        self._tray_icon: Any = None
        self._tray_hide_ok = False
        self._tray_hint_shown = False
        self.window.protocol("WM_DELETE_WINDOW", self._on_window_close)

        self._instance_server = InstanceServer(self._show_from_thread)
        if not self._instance_server.start():
            self.log("⚠ Another launcher instance seems to be running")

        self.tray_var.set(bool(self.config.get("tray")))
        if self.tray_var.get():
            self._tray_start()

    # --- checkbox -----------------------------------------------------------

    def _on_tray_toggled(self) -> None:
        """Checkbox handler: apply now and remember it (no Save needed)."""
        enabled = bool(self.tray_var.get())
        if enabled:
            if not self._tray_start():
                self.tray_var.set(False)
                return
        else:
            self._tray_stop()
        self.config["tray"] = enabled
        saved = load_config() or {}
        saved["tray"] = enabled
        save_config(saved)

    # --- icon ---------------------------------------------------------------

    def _tray_start(self) -> bool:
        if self._tray_icon is not None:
            return True
        ok, why = pystray_available()
        if not ok:
            self.log(f"✗ Tray icon unavailable ({why})")
            self.log(f"  {INSTALL_HINT}")
            return False
        import pystray
        from PIL import Image

        try:
            image = Image.open(APP_DIR / "icon.png")
        except OSError:
            image = Image.new("RGB", (64, 64), (76, 175, 80))

        def later(fn):
            # pystray calls back on its own thread; Tk work must run on the main one.
            return lambda icon, item: self.window.after(0, fn)

        menu = pystray.Menu(
            pystray.MenuItem("Show launcher", later(self.show_window), default=True),
            pystray.MenuItem(
                "Start Minecraft",
                later(self.start_minecraft),
                enabled=lambda item: not self._last_running,
            ),
            pystray.MenuItem(
                "Stop Minecraft",
                later(self.stop_minecraft),
                enabled=lambda item: bool(self._last_running),
            ),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("Quit launcher", later(self.quit_app)),
        )
        try:
            icon = pystray.Icon("minecraft-launcher", image, "Craftainer", menu)
        except Exception as e:
            self.log(f"✗ Could not create tray icon: {e}")
            return False

        backend = backend_name(icon)
        sni = sni_host_available() if backend == "appindicator" else None
        self._tray_hide_ok = can_hide_to_tray(backend, sni)
        self._tray_icon = icon
        self._tray_state: bool | None = None
        threading.Thread(target=self._tray_run, args=(icon,), daemon=True, name="tray").start()

        if self._tray_hide_ok:
            self.log(f"✓ Tray icon on ({backend}); closing the window hides it to the tray")
        else:
            self.log(
                f"⚠ Tray icon on ({backend}) but no tray host found, so closing still quits. "
                "On GNOME, enable the 'AppIndicator and KStatusNotifierItem Support' extension."
            )
        return True

    def _tray_run(self, icon: Any) -> None:
        try:
            icon.run()
        except Exception as e:
            self.window.after(0, self._tray_failed, icon, e)

    def _show_from_thread(self) -> None:
        self.window.after(0, self.show_window)

    def _tray_failed(self, icon: Any, err: Exception) -> None:
        if self._tray_icon is icon:
            self._tray_icon = None
            self._tray_hide_ok = False
            self.tray_var.set(False)
        self.log(f"✗ Tray icon stopped: {err}")
        self.show_window()

    def _tray_stop(self) -> None:
        icon, self._tray_icon = self._tray_icon, None
        self._tray_hide_ok = False
        if icon is not None:
            try:
                icon.stop()
            except Exception:
                pass
            self.log("Tray icon off")

    def _tray_sync_state(self, running: bool | None) -> None:
        """State-poll hook: refresh the menu's Start/Stop and the tooltip on a change."""
        icon = self._tray_icon
        if icon is None or getattr(self, "_tray_state", None) == running:
            return
        self._tray_state = running
        try:
            icon.title = "Craftainer: " + ("running" if running else "stopped")
            icon.update_menu()
        except Exception:
            pass

    # --- window -------------------------------------------------------------

    def show_window(self) -> None:
        self.window.deiconify()
        self.window.lift()
        try:
            self.window.focus_force()
        except tk.TclError:
            pass

    def _on_window_close(self) -> None:
        if self._tray_icon is not None and self._tray_hide_ok:
            self.window.withdraw()
            if not self._tray_hint_shown:
                self._tray_hint_shown = True
                self.log("Launcher hidden to the tray; use the tray icon to show it or quit")
            return
        self.quit_app()

    def quit_app(self) -> None:
        """Really exit: stop the tray icon and instance socket, close the window.

        The game container is left alone, as before; it keeps running if it was.
        """
        self._tray_stop()
        server = getattr(self, "_instance_server", None)
        if server is not None:
            server.close()
        self.window.destroy()
