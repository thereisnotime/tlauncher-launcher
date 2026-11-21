# mypy: disable-error-code="attr-defined, has-type"
# (mixin: self is MinecraftLauncherGUI at runtime, which mypy cannot see here)
"""Dark ttk theme, colour palette and window icon."""

import tkinter as tk
from tkinter import ttk

from ui.common import APP_DIR


class ThemeMixin:
    """Sets up ttk styles, self.colors and the window icon."""

    def _setup_theme(self):
        """Set up modern theme and colors."""
        style = ttk.Style()

        # Try to use a better theme if available
        available_themes = style.theme_names()
        if "clam" in available_themes:
            style.theme_use("clam")
        elif "alt" in available_themes:
            style.theme_use("alt")

        # Custom color scheme - Minecraft-inspired greens and modern grays
        bg_color = "#2b2b2b"  # Dark gray background
        fg_color = "#e8e8e8"  # Light text
        accent_color = "#7cbd3f"  # Minecraft grass green
        button_bg = "#3d3d3d"  # Button background
        button_active = "#4a4a4a"  # Button hover

        # Configure window background
        self.window.configure(bg=bg_color)

        # Configure styles
        style.configure("TFrame", background=bg_color)
        style.configure("TLabel", background=bg_color, foreground=fg_color, font=("Segoe UI", 10))
        style.configure(
            "TLabelframe", background=bg_color, foreground=fg_color, bordercolor=accent_color
        )
        style.configure(
            "TLabelframe.Label",
            background=bg_color,
            foreground=accent_color,
            font=("Segoe UI", 10, "bold"),
        )

        # Button styling
        style.configure(
            "TButton",
            background=button_bg,
            foreground=fg_color,
            bordercolor=accent_color,
            focuscolor=accent_color,
            font=("Segoe UI", 9),
            padding=8,
        )
        style.map(
            "TButton",
            background=[("active", button_active), ("pressed", accent_color)],
            foreground=[("active", fg_color)],
        )

        # Combobox styling
        style.configure(
            "TCombobox",
            fieldbackground=button_bg,
            background=button_bg,
            foreground=fg_color,
            arrowcolor=accent_color,
            selectbackground=accent_color,
            selectforeground=fg_color,
        )

        style.map(
            "TCombobox",
            fieldbackground=[("readonly", button_bg)],
            selectbackground=[("readonly", accent_color)],
            selectforeground=[("readonly", fg_color)],
        )

        # Configure combobox dropdown listbox colors
        self.window.option_add("*TCombobox*Listbox.background", button_bg)
        self.window.option_add("*TCombobox*Listbox.foreground", fg_color)
        self.window.option_add("*TCombobox*Listbox.selectBackground", accent_color)
        self.window.option_add("*TCombobox*Listbox.selectForeground", fg_color)
        self.window.option_add("*TCombobox*Listbox.font", ("Segoe UI", 10))

        # Configure colors for status labels
        self.colors = {
            "bg": bg_color,
            "fg": fg_color,
            "accent": accent_color,
            "success": "#4caf50",
            "warning": "#ff9800",
            "error": "#f44336",
            "info": "#2196f3",
        }

    def _set_window_icon(self):
        """Set the window icon for taskbar/dock (X11). Keeps a reference to avoid GC."""
        icon_path = APP_DIR / "icon.png"
        if not icon_path.is_file():
            return
        try:
            # Try standard Tk PhotoImage (PNG supported on many Linux Tk builds)
            self._icon_photo = tk.PhotoImage(file=str(icon_path))
            self.window.iconphoto(True, self._icon_photo)
        except tk.TclError:
            try:
                # Fallback: Pillow if installed
                from PIL import Image, ImageTk

                img = Image.open(icon_path)
                self._icon_photo = ImageTk.PhotoImage(img)
                self.window.iconphoto(True, self._icon_photo)
            except (ImportError, OSError):
                pass
