"""Typed view of the state the GUI mixins share.

Every mixin in ui/ inherits GUIBase so mypy knows what `self` holds: the
attributes gui.MinecraftLauncherGUI and the mixins set, and the methods one
mixin calls on another. It is declarations only. The attributes are bare
annotations (no class-level values) and the method stubs exist only under
TYPE_CHECKING, so at runtime GUIBase is an empty class and can never shadow a
real implementation, wherever it lands in the MRO.
"""

import tkinter as tk
from tkinter import scrolledtext, ttk
from typing import TYPE_CHECKING, Any, Callable, Dict, Optional, Tuple


class GUIBase:
    """Shared attributes and cross-mixin methods of MinecraftLauncherGUI."""

    # gui.MinecraftLauncherGUI.__init__
    window: tk.Tk
    config: Dict[str, str]
    detected: Dict[str, str]
    _cpu_cores: int
    _user_requested_stop: bool
    _transition_at: float
    _compose_install_declined: bool
    _compose_install_busy: bool

    # ThemeMixin
    colors: Dict[str, str]
    _icon_photo: Any  # tk.PhotoImage, or PIL.ImageTk.PhotoImage as a fallback

    # LayoutMixin: configuration dropdowns
    runtime_var: tk.StringVar
    runtime_combo: ttk.Combobox
    runtime_status_label: ttk.Label
    gpu_var: tk.StringVar
    gpu_combo: ttk.Combobox
    gpu_status_label: ttk.Label
    display_var: tk.StringVar
    display_combo: ttk.Combobox
    display_status_label: ttk.Label
    audio_var: tk.StringVar
    audio_combo: ttk.Combobox
    audio_status_label: ttk.Label
    java_var: tk.StringVar
    java_combo: ttk.Combobox
    memory_var: tk.StringVar
    memory_combo: ttk.Combobox

    # LayoutMixin: controls, status bar, console
    btn_start: ttk.Button
    btn_stop: ttk.Button
    btn_restart: ttk.Button
    btn_doctor: ttk.Button
    btn_save: ttk.Button
    btn_edit: ttk.Button
    btn_rebuild: ttk.Button
    btn_report_bug: ttk.Button
    status_label: ttk.Label
    _update_frame: ttk.Frame
    _update_label: ttk.Label
    docker_svc_label: ttk.Label
    podman_svc_label: ttk.Label
    log_text: scrolledtext.ScrolledText

    # ContainerStateMixin: poll jobs and cross-thread results
    _svc_poll_job: Optional[str]
    _svc_result: Optional[Tuple[bool, bool]]
    _svc_worker_busy: bool
    _state_poll_job: Optional[str]
    _last_running: Optional[bool]
    _state_worker_busy: bool

    # ResourceMonitorMixin
    _monitor_enabled: bool
    _monitor_job: Optional[str]
    btn_monitor_toggle: ttk.Button
    cpu_label: ttk.Label
    mem_label: ttk.Label
    io_read_label: ttk.Label
    io_write_label: ttk.Label
    gpu_label: ttk.Label
    monitor_status: ttk.Label

    # ProfilesMixin / ProfileImportMixin
    profiles_listbox: tk.Listbox
    _profiles_ctx_menu: tk.Menu
    _import_running: bool

    if TYPE_CHECKING:
        # Methods one mixin calls on another. Type-checking only: the real
        # implementations live in the mixin named on each line.

        # ConsoleMixin
        def log(self, message: str) -> None: ...
        def clear_logs(self) -> None: ...
        def copy_logs(self) -> None: ...
        def _update_status(self, text: str, color: str = "success") -> None: ...

        # ConfigMixin
        def _gather_config(self) -> Dict[str, Any]: ...
        def save_configuration(self) -> None: ...
        def edit_configuration(self) -> None: ...

        # ContainerStateMixin
        def _check_existing_container(self) -> None: ...

        # ContainerControlMixin
        def start_minecraft(self) -> None: ...
        def stop_minecraft(self) -> None: ...
        def restart_minecraft(self) -> None: ...
        def rebuild_image(self, then_start: bool = False) -> None: ...
        def _offer_compose_install(
            self, issues: Any, on_done: Optional[Callable[[], Any]] = None
        ) -> bool: ...

        # DoctorMixin
        def run_doctor(self) -> None: ...
        def report_bug(self) -> None: ...

        # UpdatesMixin
        def _do_update(self) -> None: ...

        # ResourceMonitorMixin / ProfilesMixin panels
        def _create_resource_monitor(self, parent_frame: ttk.Frame) -> None: ...
        def _create_profiles_panel(self, parent_frame: ttk.Frame) -> None: ...

        # ProfilesMixin / ProfileImportMixin / ProfileInfoMixin
        def refresh_profiles(self) -> None: ...
        def import_profile(self) -> None: ...
        def import_profile_from_url(self) -> None: ...
        def show_profile_info(self) -> None: ...
        def copy_profile_info(self) -> None: ...
