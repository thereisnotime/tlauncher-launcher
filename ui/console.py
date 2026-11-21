"""Console output and status label helpers."""

import tkinter as tk

from core.composer import strip_ansi


class ConsoleMixin:
    """log(), clear/copy of the console, and the coloured status label."""

    def clear_logs(self):
        """Clear the log output."""
        self.log_text.delete("1.0", tk.END)

    def copy_logs(self):
        """Copy full log content to the clipboard."""
        content = self.log_text.get("1.0", tk.END)
        if content.strip():
            self.window.clipboard_clear()
            self.window.clipboard_append(content)
            self.window.update_idletasks()
            self.log("(Logs copied to clipboard)")

    def log(self, message: str):
        """Append message to log output."""
        self.log_text.insert(tk.END, strip_ansi(message) + "\n")
        self.log_text.see(tk.END)
        self.log_text.update()

    def _update_status(self, text: str, color: str = "success"):
        """Update status label with colored indicator."""
        # Map color names to actual colors
        color_map = {
            "success": self.colors["success"],
            "green": self.colors["success"],
            "warning": self.colors["warning"],
            "orange": self.colors["warning"],
            "error": self.colors["error"],
            "red": self.colors["error"],
            "info": self.colors["info"],
            "gray": "#888888",
            "black": self.colors["fg"],
        }

        actual_color = color_map.get(color, color)

        # Add status indicator dot
        if "Running" in text:
            status_text = "● " + text.replace("Status: ", "")
        elif "Starting" in text or "Stopping" in text or "Restarting" in text:
            status_text = "◐ " + text.replace("Status: ", "")
        elif "Stopped" in text or "Ready" in text:
            status_text = "○ " + text.replace("Status: ", "")
        elif "Failed" in text or "Error" in text:
            status_text = "✗ " + text.replace("Status: ", "")
        else:
            status_text = "● " + text.replace("Status: ", "")

        self.status_label.config(text=status_text, foreground=actual_color)
