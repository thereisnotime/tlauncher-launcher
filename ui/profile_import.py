"""Profile/modpack import from a file or URL, run on a background thread."""

import json
import subprocess
import threading
import tkinter as tk
from tkinter import filedialog, messagebox, simpledialog, ttk

from core.container import build_image_command, image_exists, image_tag
from core.game_ram import get_game_ram, mem_limit_mb, set_game_ram, suggest_for_modpack
from core.packs import PackError, check_pack_update, import_archive, list_installed_packs
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
            self.window.after(0, self.log, msg)

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
        for note in result.notes:
            self.log(f"  {note}")
        messagebox.showinfo("Import Complete", msg)
        if result.kind == "mrpack":
            self._offer_game_ram(result)

    # ── Game RAM ────────────────────────────────────────────────────────────

    def _tlauncher_running(self) -> bool:
        runtime = self._gather_config().get("runtime", "podman")
        try:
            out = subprocess.run(
                [runtime, "ps", "--filter", "name=^tlauncher$", "--format", "{{.Names}}"],
                capture_output=True,
                text=True,
                timeout=10,
            ).stdout
        except (OSError, subprocess.SubprocessError):
            return False
        return "tlauncher" in out.split()

    def _offer_game_ram(self, result):
        """After a modpack import, offer a RAM setting that suits it and fits the container."""
        cap = mem_limit_mb(self._gather_config()["memory"])
        current = get_game_ram()
        mods = sum(1 for _ in (result.game_dir / "mods").glob("*.jar"))
        target = suggest_for_modpack(current, cap, mods)
        if not target:
            return
        now = f"{current} MB" if current else "TLauncher's default"
        if not messagebox.askyesno(
            "Minecraft RAM",
            f"{result.name} has {mods} mods. Give Minecraft {target} MB of RAM?\n\n"
            f"Currently: {now}. Container cap: {cap} MB.",
        ):
            return
        if self._tlauncher_running():
            messagebox.showinfo(
                "Minecraft RAM",
                "Minecraft is running, and TLauncher overwrites its settings on exit.\n"
                f"Stop it first, or set {target} MB in TLauncher's settings.",
            )
            return
        set_game_ram(target)
        self.log(f"✓ Minecraft RAM set to {target} MB")

    # ── Modpack updates ─────────────────────────────────────────────────────

    def _selected_pack(self):
        """The imported modpack behind the selected profile, if any."""
        packs = list_installed_packs()
        selection = self.profiles_listbox.curselection()
        if not selection:
            return packs[0] if len(packs) == 1 else None
        try:
            with open(APP_DIR / "home" / "launcher_profiles.json") as f:
                profiles = list(json.load(f).get("profiles", {}).values())
            profile = profiles[selection[0]]
        except (OSError, ValueError, IndexError):
            return None
        vid = profile.get("lastVersionId", "")
        return next(
            (p for p in packs if p.version_id == vid or p.name == profile.get("name")), None
        )

    def update_selected_pack(self):
        """Check the selected profile's modpack for a new version and install it."""
        pack = self._selected_pack()
        if pack is None:
            messagebox.showinfo(
                "Update pack", "Select a profile that was imported from a .mrpack modpack."
            )
            return
        self.log(f"\n🔎 Checking {pack.name} for updates...")

        def worker():
            try:
                new = check_pack_update(pack)
            except PackError as e:
                err = str(e)
                self.window.after(0, lambda: messagebox.showerror("Update pack", err))
                return

            def done():
                if not new:
                    self.log(f"✓ {pack.name} {pack.version} is up to date".replace("  ", " "))
                    messagebox.showinfo("Update pack", f"{pack.name} is up to date.")
                    return
                self.log(f"⬆ {pack.name}: {pack.version or '?'} -> {new}")
                self._start_import(pack.source)

            self.window.after(0, done)

        threading.Thread(target=worker, daemon=True).start()

    def _check_pack_updates_async(self):
        """On startup: quietly check imported packs that came from a URL."""

        def worker():
            updates = []
            for pack in list_installed_packs():
                if not pack.source.lower().startswith(("http://", "https://")):
                    continue
                try:
                    new = check_pack_update(pack)
                except PackError:
                    continue
                if new:
                    updates.append((pack, new))
            if updates:
                self.window.after(0, lambda: self._offer_pack_updates(updates))

        threading.Thread(target=worker, daemon=True).start()

    def _offer_pack_updates(self, updates):
        lines = "\n".join(f"  • {p.name}: {p.version or '?'} -> {new}" for p, new in updates)
        self.log(f"\n⬆ Modpack update available:\n{lines}")
        if getattr(self, "_import_running", False) or self._tlauncher_running():
            return  # don't swap mods under a running game; the log line is enough
        if messagebox.askyesno("Modpack update", f"New version available:\n{lines}\n\nUpdate now?"):
            for pack, _new in updates[:1]:
                self._start_import(pack.source)

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
        box: dict[str, str | None] = {"v": None}

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
