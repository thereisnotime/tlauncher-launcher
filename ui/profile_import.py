"""Profile/modpack import from a file or URL, run on a background thread."""

import subprocess
import threading
import tkinter as tk
from tkinter import filedialog, messagebox, simpledialog, ttk

from core.container import build_image_command, image_exists, image_tag
from core.packs import PackError, import_archive
from ui.base import GUIBase
from ui.common import APP_DIR


class ProfileImportMixin(GUIBase):
    """Import from file or URL (.mrpack, .mcprofile.zip, mods zip) and the mods-target dialog."""

    def import_profile(self):
        """Import a modpack/profile/mods zip from a local file (file picker)."""

        path = filedialog.askopenfilename(
            title="Select a modpack, profile or mods zip",
            filetypes=[
                ("Modpacks and profiles", "*.mrpack *.zip"),
                ("Modrinth modpack", "*.mrpack"),
                ("ZIP files", "*.zip"),
                ("All files", "*.*"),
            ],
        )
        if path:
            self._start_import(path)

    def import_profile_from_url(self):
        """Import from a URL: paste the link, OK, done."""

        url = simpledialog.askstring(
            "Import from URL",
            "Paste a link to a .mrpack modpack, a mods .zip or a .mcprofile.zip.\n"
            "Google Drive, Dropbox and GitHub share links work too.",
            parent=self.window,
        )
        if not url:
            return
        url = url.strip()
        if not url.lower().startswith(("http://", "https://")):
            messagebox.showerror("Invalid URL", "Please enter an http:// or https:// URL.")
            return
        self._start_import(url)

    def _start_import(self, source: str):
        """Run an import in a background thread, logging progress to the GUI."""

        if getattr(self, "_import_running", False):
            messagebox.showinfo("Import running", "An import is already in progress.")
            return
        self._import_running = True
        config = self._gather_config()
        runtime, java = config.get("runtime", "podman"), config["java"]

        def log(msg):
            self.window.after(0, lambda m=msg: self.log(m))

        def choose_target(versions):
            # Plain mods zip: ask on the main thread which version gets the mods.
            done = threading.Event()
            box = {}

            def ask():
                box["v"] = self._ask_mods_target(versions)
                done.set()

            self.window.after(0, ask)
            done.wait()
            return box.get("v")

        def worker():
            try:
                if not image_exists(runtime, java):
                    # Needed for Forge/NeoForge installers; same image as Start.
                    log(f"Building {image_tag(java)} first (one time)...")
                    proc = subprocess.Popen(
                        build_image_command(runtime, java),
                        stdout=subprocess.PIPE,
                        stderr=subprocess.STDOUT,
                        text=True,
                        cwd=str(APP_DIR),
                    )
                    for line in proc.stdout:
                        log(line.rstrip())
                    if proc.wait() != 0:
                        raise PackError("Image build failed")
                result = import_archive(
                    source,
                    runtime=runtime,
                    image=image_tag(java),
                    log=log,
                    choose_target=choose_target,
                )
            except Exception as e:  # noqa: BLE001 (surface every failure to the user)
                err = str(e)
                self.window.after(0, lambda: self._import_finished(None, err))
                return
            self.window.after(0, lambda: self._import_finished(result, None))

        self.log(f"\n{'=' * 50}\n📥 Importing {source}")
        threading.Thread(target=worker, daemon=True).start()

    def _import_finished(self, result, error):
        self._import_running = False
        if error:
            self.log(f"✗ Import failed: {error}")
            if error != "Import cancelled":
                messagebox.showerror("Import Failed", error)
            return
        self.log(f"✓ Imported {result.name} ({result.files} files)")
        self.refresh_profiles()
        if result.kind == "mrpack":
            msg = (
                f"{result.name} is installed.\n\n"
                f"Start the launcher, pick {result.version_id} in TLauncher and play."
            )
        elif result.kind == "mods":
            where = result.version_id or "the shared mods folder"
            msg = f"Installed {result.files} file(s) into {where}."
        else:
            msg = f"Profile '{result.name}' imported."
        messagebox.showinfo("Import Complete", msg)

    def _ask_mods_target(self, versions):
        """Dialog: which installed version gets a plain mods zip. None = cancel."""
        win = tk.Toplevel(self.window)
        win.title("Install mods into...")
        win.configure(bg=self.colors["bg"])
        win.transient(self.window)
        win.grab_set()
        ttk.Label(
            win,
            text="This zip only contains mods. Which version should get them?",
            padding=10,
        ).pack(anchor=tk.W)
        choices = versions + ["Shared mods folder (all versions)"]
        listbox = tk.Listbox(win, height=min(10, len(choices)), width=48)
        for c in choices:
            listbox.insert(tk.END, c)
        listbox.selection_set(0)
        listbox.pack(fill=tk.BOTH, expand=True, padx=10)
        box = {"v": None}

        def ok():
            sel = listbox.curselection()
            if sel:
                box["v"] = "" if sel[0] == len(versions) else versions[sel[0]]
            win.destroy()

        btns = ttk.Frame(win, padding=10)
        btns.pack(fill=tk.X)
        ttk.Button(btns, text="Install", command=ok).pack(side=tk.RIGHT)
        ttk.Button(btns, text="Cancel", command=win.destroy).pack(side=tk.RIGHT, padx=6)
        listbox.bind("<Double-Button-1>", lambda _e: ok())
        self.window.wait_window(win)
        return box["v"]
