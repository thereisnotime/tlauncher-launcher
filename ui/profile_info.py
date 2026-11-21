"""Profile details: loader, versions and mod list, as a window or clipboard text."""

import json
import re
import tkinter as tk
from tkinter import messagebox, ttk

from ui.base import GUIBase
from ui.common import APP_DIR


class ProfileInfoMixin(GUIBase):
    """Collects a profile's details and shows them (Info window) or copies them (Copy Info)."""

    def _collect_profile_info(self, selected_idx):
        """Gather all info + mods for the profile at the given listbox index.

        Returns a dict of the parsed fields, or None if the index is invalid.
        Raises on unexpected errors so the caller can surface them.
        """

        profiles_file = APP_DIR / "home" / "launcher_profiles.json"
        with open(profiles_file) as f:
            data = json.load(f)

        profiles = data.get("profiles", {})
        profile_keys = list(profiles.keys())
        if selected_idx >= len(profile_keys):
            return None

        profile_id = profile_keys[selected_idx]
        profile_data = profiles[profile_id]
        profile_name = profile_data.get("name", profile_id)
        version_id = profile_data.get("lastVersionId", "unknown")
        profile_type = profile_data.get("type", "custom")
        game_dir = profile_data.get("gameDir", "")

        version_dir = APP_DIR / "home" / "versions" / version_id

        # Parse version JSON for modloader and Java version
        modloader = "Vanilla"
        modloader_version = ""
        java_version = "?"
        mc_version = version_id

        version_json = version_dir / f"{version_id}.json"
        if version_json.exists():
            with open(version_json) as f:
                vdata = json.load(f)
            java_version = str(vdata.get("javaVersion", {}).get("majorVersion", "?"))
            libs = [lib["name"] for lib in vdata.get("libraries", [])]
            if any("neoforged" in lib for lib in libs):
                modloader = "NeoForge"
            elif any("net.minecraftforge:forge:" in lib for lib in libs):
                modloader = "Forge"
            elif any("net.fabricmc:fabric-loader:" in lib for lib in libs):
                modloader = "Fabric"
            elif any("org.quiltmc:quilt-loader:" in lib for lib in libs):
                modloader = "Quilt"

        # Refine MC version and modloader version from TLauncherAdditional.json
        tl_additional = version_dir / "TLauncherAdditional.json"
        if tl_additional.exists():
            with open(tl_additional) as f:
                tl_data = json.load(f)
            paths = [x["path"] for x in tl_data.get("additionalFiles", [])]
            for p in paths:
                m = re.search(r"net/minecraft/client/(\d+\.\d+[\.\d]*)", p)
                if m:
                    mc_version = m.group(1)
                    break
            patterns = {
                "NeoForge": r"net/neoforged/neoforge/([^/]+)",
                "Forge": r"net/minecraftforge/forge/([^/]+)",
                "Fabric": r"net/fabricmc/fabric-loader/([^/]+)",
                "Quilt": r"org/quiltmc/quilt-loader/([^/]+)",
            }
            if modloader in patterns:
                for p in paths:
                    m = re.search(patterns[modloader], p)
                    if m:
                        modloader_version = m.group(1)
                        break

        # Resolve mods directory on host
        if game_dir.startswith("/home/app/.minecraft/"):
            rel = game_dir.replace("/home/app/.minecraft/", "")
            mods_dir = APP_DIR / "home" / rel / "mods"
        else:
            mods_dir = APP_DIR / "home" / "mods"

        active_mods = []
        disabled_mods = []
        if mods_dir.exists():
            for entry in sorted(mods_dir.iterdir()):
                name = entry.name
                if name.endswith(".jar.deactivation"):
                    disabled_mods.append(name[: -len(".deactivation")])
                elif name.endswith(".jar"):
                    active_mods.append(name)

        return {
            "profile_name": profile_name,
            "profile_type": profile_type,
            "mc_version": mc_version,
            "modloader": modloader,
            "modloader_version": modloader_version,
            "java_version": java_version,
            "version_id": version_id,
            "active_mods": active_mods,
            "disabled_mods": disabled_mods,
        }

    def _format_profile_info_text(self, info):
        """Render a profile info dict as a plain-text block for the clipboard."""
        ml_label = f"{info['modloader']} {info['modloader_version']}".strip()
        active = info["active_mods"]
        disabled = info["disabled_mods"]
        total = len(active) + len(disabled)

        lines = [
            f"Profile:    {info['profile_name']}",
            f"Type:       {info['profile_type']}",
            f"MC Version: {info['mc_version']}",
            f"Modloader:  {ml_label}",
            f"Java:       Java {info['java_version']}",
            f"Version ID: {info['version_id']}",
            "",
            f"Mods total: {total}  (active: {len(active)}, disabled: {len(disabled)})",
        ]
        if active or disabled:
            lines.append("")
            lines.append("Mods:")
            for name in active:
                lines.append(f"  [x] {name}")
            for name in disabled:
                lines.append(f"  [ ] {name}")
        return "\n".join(lines)

    def copy_profile_info(self):
        """Copy the selected profile's full info + mod list to the clipboard."""

        selection = self.profiles_listbox.curselection()
        if not selection:
            messagebox.showwarning("No Selection", "Please select a profile to copy its info.")
            return
        try:
            info = self._collect_profile_info(selection[0])
            if info is None:
                messagebox.showerror("Error", "Invalid profile selection.")
                return
            text = self._format_profile_info_text(info)
            self.window.clipboard_clear()
            self.window.clipboard_append(text)
            self.window.update_idletasks()
            self.log(f"(Copied info for '{info['profile_name']}' to clipboard)")
        except Exception as e:
            messagebox.showerror("Error", f"Could not copy profile info:\n{e}")

    def show_profile_info(self):
        """Show detailed info for the selected profile."""

        selection = self.profiles_listbox.curselection()
        if not selection:
            messagebox.showwarning("No Selection", "Please select a profile to view its info.")
            return

        try:
            info = self._collect_profile_info(selection[0])
            if info is None:
                messagebox.showerror("Error", "Invalid profile selection.")
                return

            profile_name = info["profile_name"]
            profile_type = info["profile_type"]
            mc_version = info["mc_version"]
            modloader = info["modloader"]
            modloader_version = info["modloader_version"]
            java_version = info["java_version"]
            version_id = info["version_id"]
            active_mods = info["active_mods"]
            disabled_mods = info["disabled_mods"]

            # Build info window
            win = tk.Toplevel(self.window)
            win.title(f"Profile Info — {profile_name}")
            win.resizable(True, True)
            win.minsize(480, 300)
            win.configure(bg="#1e1e1e")

            frame = ttk.Frame(win, padding=16)
            frame.pack(fill=tk.BOTH, expand=True)

            def info_row(label, value, value_fg="#d4d4d4"):
                r = ttk.Frame(frame)
                r.pack(fill=tk.X, pady=1)
                tk.Label(
                    r,
                    text=f"{label:<18}",
                    bg="#1e1e1e",
                    fg="#888888",
                    font=("Courier New", 9),
                    anchor="w",
                ).pack(side=tk.LEFT)
                tk.Label(
                    r,
                    text=value,
                    bg="#1e1e1e",
                    fg=value_fg,
                    font=("Courier New", 9, "bold"),
                    anchor="w",
                ).pack(side=tk.LEFT)

            info_row("Profile", profile_name)
            info_row("Type", profile_type)
            info_row("MC Version", mc_version, "#7cbd3f")
            ml_label = f"{modloader} {modloader_version}".strip()
            info_row("Modloader", ml_label, "#7cbd3f" if modloader != "Vanilla" else "#d4d4d4")
            info_row("Java", f"Java {java_version}")
            info_row("Version ID", version_id)

            ttk.Separator(frame, orient="horizontal").pack(fill=tk.X, pady=(8, 6))

            total = len(active_mods) + len(disabled_mods)
            info_row("Mods total", str(total))
            info_row("  Active", str(len(active_mods)), "#7cbd3f")
            info_row(
                "  Disabled",
                str(len(disabled_mods)),
                "#e57373" if disabled_mods else "#d4d4d4",
            )

            if active_mods or disabled_mods:
                ttk.Separator(frame, orient="horizontal").pack(fill=tk.X, pady=(8, 4))
                tk.Label(
                    frame,
                    text="Mods:",
                    bg="#1e1e1e",
                    fg="#888888",
                    font=("Courier New", 9),
                    anchor="w",
                ).pack(fill=tk.X)

                mod_list_frame = ttk.Frame(frame)
                mod_list_frame.pack(fill=tk.BOTH, expand=True, pady=(4, 0))

                sb = ttk.Scrollbar(mod_list_frame)
                sb.pack(side=tk.RIGHT, fill=tk.Y)

                lb = tk.Listbox(
                    mod_list_frame,
                    yscrollcommand=sb.set,
                    bg="#252525",
                    fg="#d4d4d4",
                    font=("Courier New", 8),
                    height=min(14, total),
                    relief=tk.FLAT,
                    borderwidth=0,
                    selectbackground="#333333",
                )
                lb.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
                sb.config(command=lb.yview)

                for name in active_mods:
                    lb.insert(tk.END, f"  ✓  {name}")
                    lb.itemconfig(tk.END, fg="#7cbd3f")
                for name in disabled_mods:
                    lb.insert(tk.END, f"  ✗  {name}")
                    lb.itemconfig(tk.END, fg="#888888")

            btn_row = ttk.Frame(frame)
            btn_row.pack(fill=tk.X, pady=(12, 0))
            ttk.Button(
                btn_row,
                text="📋 Copy Info",
                command=self.copy_profile_info,
                width=14,
            ).pack(side=tk.LEFT)
            ttk.Button(btn_row, text="Close", command=win.destroy, width=10).pack(side=tk.RIGHT)

            win.update_idletasks()
            # Size to content, but clamp to the screen so the buttons are never
            # pushed off the bottom on QHD/HiDPI. The mod list expands/scrolls to
            # absorb any overflow, keeping the button row visible.
            sw = win.winfo_screenwidth()
            sh = win.winfo_screenheight()
            w = min(max(win.winfo_reqwidth(), 520), sw - 80)
            h = min(win.winfo_reqheight(), sh - 120)
            x = self.window.winfo_x() + (self.window.winfo_width() - w) // 2
            y = self.window.winfo_y() + (self.window.winfo_height() - h) // 2
            x = max(0, min(x, sw - w))
            y = max(0, min(y, sh - h))
            win.geometry(f"{w}x{h}+{x}+{y}")

        except Exception as e:
            messagebox.showerror("Error", f"Could not load profile info:\n{e}")
