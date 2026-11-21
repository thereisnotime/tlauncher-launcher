# mypy: disable-error-code="attr-defined, has-type"
# (mixin: self is MinecraftLauncherGUI at runtime, which mypy cannot see here)
"""Minecraft Profiles panel: list, export, delete, open folder, help."""

import json
import os
import subprocess
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

from core.packs import PackError, export_profile
from ui.common import APP_DIR


class ProfilesMixin:
    """Profiles list, its buttons and right-click menu, and the per-profile actions."""

    def _create_profiles_panel(self, parent_frame):
        """Create profiles management panel."""
        profiles_frame = ttk.LabelFrame(parent_frame, text="📦 Minecraft Profiles", padding="10")
        profiles_frame.grid(row=1, column=0, sticky=(tk.W, tk.E, tk.N, tk.S))

        # Buttons frame — 5 equal columns, fills full width
        btn_frame = ttk.Frame(profiles_frame)
        btn_frame.pack(fill=tk.X, pady=(0, 8))
        for _col in range(5):
            btn_frame.columnconfigure(_col, weight=1)

        btn_import = ttk.Button(btn_frame, text="📥 File", command=self.import_profile)
        btn_import.grid(row=0, column=0, sticky=(tk.W, tk.E), padx=(0, 4))

        btn_import_url = ttk.Button(btn_frame, text="🌐 URL", command=self.import_profile_from_url)
        btn_import_url.grid(row=0, column=1, sticky=(tk.W, tk.E), padx=4)

        btn_refresh = ttk.Button(btn_frame, text="🔄 Refresh", command=self.refresh_profiles)
        btn_refresh.grid(row=0, column=2, sticky=(tk.W, tk.E), padx=4)

        btn_help = ttk.Button(btn_frame, text="?", command=self.show_profile_help)
        btn_help.grid(row=0, column=3, sticky=(tk.W, tk.E), padx=4)

        btn_info = ttk.Button(btn_frame, text="📋 Info", command=self.show_profile_info)
        btn_info.grid(row=0, column=4, sticky=(tk.W, tk.E), padx=(4, 0))

        # Profiles list with scrollbar
        list_frame = ttk.Frame(profiles_frame)
        list_frame.pack(fill=tk.BOTH, expand=True)

        scrollbar = ttk.Scrollbar(list_frame)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)

        self.profiles_listbox = tk.Listbox(
            list_frame,
            yscrollcommand=scrollbar.set,
            bg="#1e1e1e",
            fg="#d4d4d4",
            selectbackground="#7cbd3f",
            selectforeground="#1e1e1e",
            font=("Segoe UI", 9),
            height=8,
            relief=tk.FLAT,
            borderwidth=0,
        )
        self.profiles_listbox.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scrollbar.config(command=self.profiles_listbox.yview)

        # Right-click context menu
        self._profiles_ctx_menu = tk.Menu(
            self.window,
            tearoff=0,
            bg="#2d2d2d",
            fg="#d4d4d4",
            activebackground="#7cbd3f",
            activeforeground="#1e1e1e",
            bd=0,
        )
        self._profiles_ctx_menu.add_command(label="📋 Info", command=self.show_profile_info)
        self._profiles_ctx_menu.add_command(label="📄 Copy Info", command=self.copy_profile_info)
        self._profiles_ctx_menu.add_command(
            label="📁 Open Folder", command=self.open_profile_folder
        )
        self._profiles_ctx_menu.add_command(label="📤 Export", command=self.export_profile)
        self._profiles_ctx_menu.add_separator()
        self._profiles_ctx_menu.add_command(label="📥 Import", command=self.import_profile)
        self._profiles_ctx_menu.add_command(label="🔄 Refresh", command=self.refresh_profiles)
        self._profiles_ctx_menu.add_separator()
        self._profiles_ctx_menu.add_command(label="🗑 Delete", command=self.delete_profile)
        # Bind on button RELEASE, not press: posting the menu while the right
        # button is still held makes Tk treat it as a press-drag-release menu
        # (you have to hold it open, and releasing over an item triggers it).
        self.profiles_listbox.bind("<ButtonRelease-3>", self._show_profiles_context_menu)

        # Profile action buttons — 3 equal columns, fills full width
        action_frame = ttk.Frame(profiles_frame)
        action_frame.pack(fill=tk.X, pady=(8, 0))
        for _col in range(4):
            action_frame.columnconfigure(_col, weight=1)

        btn_export = ttk.Button(action_frame, text="📤 Export", command=self.export_profile)
        btn_export.grid(row=0, column=0, sticky=(tk.W, tk.E), padx=(0, 4))

        btn_open_folder = ttk.Button(
            action_frame, text="📁 Open Folder", command=self.open_profile_folder
        )
        btn_open_folder.grid(row=0, column=1, sticky=(tk.W, tk.E), padx=4)

        btn_delete = ttk.Button(action_frame, text="🗑 Delete", command=self.delete_profile)
        btn_delete.grid(row=0, column=2, sticky=(tk.W, tk.E), padx=4)

        btn_update_pack = ttk.Button(
            action_frame, text="⬆ Update pack", command=self.update_selected_pack
        )
        btn_update_pack.grid(row=0, column=3, sticky=(tk.W, tk.E), padx=(4, 0))

        # Load profiles
        self.refresh_profiles()

    @staticmethod
    def _profile_disk_size(profile_data: dict, base: "Path") -> int:
        """Return total bytes used by a profile's version directory."""

        version_id = profile_data.get("lastVersionId", "")
        game_dir = profile_data.get("gameDir", "")
        if game_dir and game_dir.startswith("/home/app/.minecraft/"):
            rel = game_dir[len("/home/app/.minecraft/") :]
            candidate = base / rel
        else:
            candidate = base / "versions" / version_id

        if not candidate.is_dir():
            return 0

        total = 0
        for dirpath, _, filenames in os.walk(candidate):
            for fname in filenames:
                try:
                    total += (Path(dirpath) / fname).stat().st_size
                except OSError:
                    pass
        return total

    @staticmethod
    def _fmt_size(size_bytes: int) -> str:
        if size_bytes == 0:
            return "—"
        for unit, threshold in (("GB", 1 << 30), ("MB", 1 << 20), ("KB", 1 << 10)):
            if size_bytes >= threshold:
                return f"{size_bytes / threshold:.1f} {unit}"
        return f"{size_bytes} B"

    def refresh_profiles(self):
        """Refresh the profiles list."""

        self.profiles_listbox.delete(0, tk.END)

        try:
            profiles_file = APP_DIR / "home" / "launcher_profiles.json"
            if not profiles_file.exists():
                self.profiles_listbox.insert(tk.END, "(No profiles found)")
                return

            with open(profiles_file) as f:
                data = json.load(f)

            profiles = data.get("profiles", {})
            if not profiles:
                self.profiles_listbox.insert(tk.END, "(No profiles found)")
                return

            base = APP_DIR / "home"
            for profile_id, profile_data in profiles.items():
                name = profile_data.get("name", profile_id)
                version = profile_data.get("lastVersionId", "unknown")
                profile_type = profile_data.get("type", "custom")
                size_str = self._fmt_size(self._profile_disk_size(profile_data, base))

                display_text = f"{name} (v{version}) [{profile_type}]  {size_str}"
                self.profiles_listbox.insert(tk.END, display_text)

                self.profiles_listbox.itemconfig(
                    tk.END,
                    fg="#7cbd3f"
                    if profile_data.get("name") == data.get("selectedProfile")
                    else "#d4d4d4",
                )

        except Exception as e:
            self.log(f"Error loading profiles: {e}")
            self.profiles_listbox.insert(tk.END, f"(Error: {e})")

    def export_profile(self):
        """Export the selected profile (version files + its mods/configs) to a ZIP."""

        selection = self.profiles_listbox.curselection()
        if not selection:
            messagebox.showwarning("No Selection", "Please select a profile to export.")
            return

        try:
            profiles_file = APP_DIR / "home" / "launcher_profiles.json"
            with open(profiles_file) as f:
                profiles = json.load(f).get("profiles", {})
            profile_keys = list(profiles.keys())
            if selection[0] >= len(profile_keys):
                messagebox.showerror("Error", "Invalid profile selection.")
                return
            profile_id = profile_keys[selection[0]]
            profile_data = profiles[profile_id]
            profile_name = profile_data.get("name", profile_id)
            version_id = profile_data.get("lastVersionId", "unknown")

            save_path = filedialog.asksaveasfilename(
                defaultextension=".zip",
                initialfile=f"{profile_name}_{version_id}.mcprofile.zip".replace("/", "_"),
                filetypes=[("Minecraft Profile", "*.mcprofile.zip"), ("ZIP files", "*.zip")],
            )
            if not save_path:
                return

            self.log(f"\n📤 Exporting profile: {profile_name}")
            export_profile(profile_id, save_path, log=self.log)
            self.log(f"✓ Profile exported to: {save_path}")
            messagebox.showinfo("Export Complete", f"Profile exported to:\n{save_path}")
        except (PackError, OSError, ValueError) as e:
            self.log(f"✗ Export failed: {e}")
            messagebox.showerror("Export Failed", f"Failed to export profile:\n{e}")

    def delete_profile(self):
        """Delete selected profile."""

        # Get selected profile
        selection = self.profiles_listbox.curselection()
        if not selection:
            messagebox.showwarning("No Selection", "Please select a profile to delete.")
            return

        try:
            # Read launcher_profiles.json
            profiles_file = APP_DIR / "home" / "launcher_profiles.json"
            with open(profiles_file) as f:
                data = json.load(f)

            profiles = data.get("profiles", {})
            profile_keys = list(profiles.keys())
            selected_idx = selection[0]

            if selected_idx >= len(profile_keys):
                messagebox.showerror("Error", "Invalid profile selection.")
                return

            profile_id = profile_keys[selected_idx]
            profile_data = profiles[profile_id]
            profile_name = profile_data.get("name", profile_id)

            # Confirm deletion
            confirm = messagebox.askyesno(
                "Confirm Deletion",
                f"Delete profile '{profile_name}'?\n\n"
                f"This will remove the profile entry from TLauncher.\n"
                f"Version files will NOT be deleted.",
            )

            if not confirm:
                return

            # Remove from profiles
            del profiles[profile_id]

            # Update selected profile if needed
            if data.get("selectedProfile") == profile_id:
                # Select first remaining profile or None
                if profiles:
                    data["selectedProfile"] = list(profiles.keys())[0]
                else:
                    data["selectedProfile"] = None

            # Save
            with open(profiles_file, "w") as f:
                json.dump(data, f, indent=2)

            self.log(f"\n🗑 Deleted profile: {profile_name}")
            messagebox.showinfo("Profile Deleted", f"Profile '{profile_name}' has been deleted.")

            # Refresh list
            self.refresh_profiles()

        except Exception as e:
            self.log(f"✗ Delete failed: {e}")
            messagebox.showerror("Delete Failed", f"Failed to delete profile:\n{e}")

    def _show_profiles_context_menu(self, event):
        """Select the item under the cursor and show the right-click context menu."""
        idx = self.profiles_listbox.nearest(event.y)
        if idx >= 0:
            self.profiles_listbox.selection_clear(0, tk.END)
            self.profiles_listbox.selection_set(idx)
            self.profiles_listbox.activate(idx)
        # Post the menu and let its own grab handle dismissal. Do NOT call
        # grab_release() right after: on some Linux/XWayland window managers that
        # eager release drops the grab that closes the menu when you click away.
        self._profiles_ctx_menu.tk_popup(event.x_root, event.y_root)

    def open_profile_folder(self):
        """Open the selected profile's version folder in the file manager."""

        selection = self.profiles_listbox.curselection()
        if not selection:
            messagebox.showwarning("No Selection", "Please select a profile to open its folder.")
            return

        try:
            profiles_file = APP_DIR / "home" / "launcher_profiles.json"
            with open(profiles_file) as f:
                data = json.load(f)

            profiles = data.get("profiles", {})
            profile_keys = list(profiles.keys())
            selected_idx = selection[0]

            if selected_idx >= len(profile_keys):
                messagebox.showerror("Error", "Invalid profile selection.")
                return

            profile_data = profiles[profile_keys[selected_idx]]
            version_id = profile_data.get("lastVersionId", "unknown")

            folder = APP_DIR / "home" / "versions" / version_id
            folder.mkdir(parents=True, exist_ok=True)

            subprocess.Popen(["xdg-open", str(folder)])

        except Exception as e:
            messagebox.showerror("Error", f"Could not open folder:\n{e}")

    def show_profile_help(self):
        """Show a help dialog explaining import/export and manual import."""

        win = tk.Toplevel(self.window)
        win.title("Profile Import & Export Help")
        win.resizable(True, True)
        win.configure(bg="#1e1e1e")
        win.minsize(560, 400)

        text = (
            "EXPORT\n"
            "──────\n"
            "Select a profile and click Export. A .mcprofile.zip file is saved to a\n"
            "location you choose. It contains:\n"
            "  • profile_metadata.json  — profile name, version, settings\n"
            "  • version/               — the version folder (incl. its mods/configs)\n"
            "  • gamedata/              — the profile's game folder, or the shared\n"
            "                             mods/ and config/ if it has none\n\n"
            "IMPORT  (📥 File or 🌐 URL)\n"
            "──────\n"
            "Accepts three kinds of archive, detected automatically:\n"
            "  • .mrpack (Modrinth modpack): installs the loader (NeoForge, Forge,\n"
            "    Fabric, Quilt), downloads every mod with checksum checks, applies\n"
            "    the pack's files (e.g. servers.dat) and adds a profile.\n"
            "  • .mcprofile.zip: a profile exported from this launcher.\n"
            "  • a plain .zip of mods: you pick which installed version gets them.\n"
            "URLs can be direct links or Google Drive / Dropbox / GitHub share links.\n"
            "Importing a newer version of the same .mrpack removes mods it dropped.\n\n"
            "MANUAL IMPORT\n"
            "─────────────\n"
            "If you have version files but no .mcprofile.zip:\n\n"
            "  1. Copy the version folder into the launcher's versions directory:\n"
            "       Linux:   <launcher-dir>/home/versions/<version>/\n"
            "       Windows: <launcher-dir>\\home\\versions\\<version>\\\n"
            "     (must contain the .jar and .json for that version)\n\n"
            "  2. Open the profiles file in a text editor:\n"
            "       Linux:   <launcher-dir>/home/launcher_profiles.json\n"
            "       Windows: <launcher-dir>\\home\\launcher_profiles.json\n\n"
            '  3. Add an entry under "profiles":\n'
            '       "MyProfile": {\n'
            '         "name": "MyProfile",\n'
            '         "type": "custom",\n'
            '         "lastVersionId": "<version>",\n'
            '         "created": "2024-01-01T00:00:00.000Z",\n'
            '         "lastUsed":  "2024-01-01T00:00:00.000Z"\n'
            "       }\n\n"
            "  4. Click Refresh in the launcher."
        )

        frame = ttk.Frame(win, padding=16)
        frame.pack(fill=tk.BOTH, expand=True)

        lbl = tk.Label(
            frame,
            text=text,
            justify=tk.LEFT,
            bg="#1e1e1e",
            fg="#d4d4d4",
            font=("Courier New", 9),
            anchor="w",
        )
        lbl.pack(anchor="w", fill=tk.X)

        ttk.Button(frame, text="Close", command=win.destroy, width=10).pack(
            anchor="e", pady=(12, 0)
        )

        win.update_idletasks()
        x = self.window.winfo_x() + (self.window.winfo_width() - win.winfo_width()) // 2
        y = self.window.winfo_y() + (self.window.winfo_height() - win.winfo_height()) // 2
        win.geometry(f"+{x}+{y}")
