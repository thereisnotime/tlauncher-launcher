"""Resource monitor panel: container CPU/RAM/network/GPU stats."""

import json
import re
import subprocess
import tkinter as tk
from tkinter import ttk

from ui.base import GUIBase


class ResourceMonitorMixin(GUIBase):
    """Resource Monitor panel and its 2s polling of `<runtime> stats`."""

    def _create_resource_monitor(self, parent_frame):
        """Create resource monitoring panel."""
        monitor_frame = ttk.LabelFrame(parent_frame, text="📊 Resource Monitor", padding="10")
        monitor_frame.grid(row=0, column=0, sticky=(tk.W, tk.E, tk.N), pady=(0, 10))
        parent_frame.rowconfigure(0, weight=0)  # Don't expand
        parent_frame.rowconfigure(1, weight=1)  # Profiles panel expands
        parent_frame.columnconfigure(0, weight=1)

        # Toggle button (smaller)
        self.btn_monitor_toggle = ttk.Button(
            monitor_frame, text="Enable Monitor", command=self.toggle_monitor
        )
        # Right-align so it lines up vertically with the profiles' Info button.
        self.btn_monitor_toggle.pack(anchor=tk.E, pady=(0, 8))

        # Stats display with proper grid configuration
        stats_frame = ttk.Frame(monitor_frame)
        stats_frame.pack(fill=tk.BOTH, expand=True)

        # Configure grid columns for proper alignment
        stats_frame.columnconfigure(0, weight=0, minsize=70)  # Label column (fixed width)
        stats_frame.columnconfigure(1, weight=1)  # Value column (expands)

        # CPU
        ttk.Label(stats_frame, text="CPU:", font=("Segoe UI", 9, "bold")).grid(
            row=0, column=0, sticky=tk.W, pady=4
        )
        self.cpu_label = ttk.Label(
            stats_frame, text="--", font=("Consolas", 8), foreground=self.colors["info"]
        )
        self.cpu_label.grid(row=0, column=1, sticky=tk.W, padx=(5, 0))

        # Memory
        ttk.Label(stats_frame, text="RAM:", font=("Segoe UI", 9, "bold")).grid(
            row=1, column=0, sticky=tk.W, pady=4
        )
        self.mem_label = ttk.Label(
            stats_frame, text="--", font=("Consolas", 8), foreground=self.colors["info"]
        )
        self.mem_label.grid(row=1, column=1, sticky=tk.W, padx=(5, 0))

        # I/O Read
        ttk.Label(stats_frame, text="Net In:", font=("Segoe UI", 9, "bold")).grid(
            row=2, column=0, sticky=tk.W, pady=4
        )
        self.io_read_label = ttk.Label(
            stats_frame, text="--", font=("Consolas", 8), foreground=self.colors["info"]
        )
        self.io_read_label.grid(row=2, column=1, sticky=tk.W, padx=(5, 0))

        # I/O Write
        ttk.Label(stats_frame, text="Net Out:", font=("Segoe UI", 9, "bold")).grid(
            row=3, column=0, sticky=tk.W, pady=4
        )
        self.io_write_label = ttk.Label(
            stats_frame, text="--", font=("Consolas", 8), foreground=self.colors["info"]
        )
        self.io_write_label.grid(row=3, column=1, sticky=tk.W, padx=(5, 0))

        # GPU (if available)
        ttk.Label(stats_frame, text="GPU:", font=("Segoe UI", 9, "bold")).grid(
            row=4, column=0, sticky=tk.W, pady=4
        )
        self.gpu_label = ttk.Label(
            stats_frame, text="--", font=("Consolas", 8), foreground=self.colors["info"]
        )
        self.gpu_label.grid(row=4, column=1, sticky=tk.W, padx=(5, 0))

        # Status
        self.monitor_status = ttk.Label(
            monitor_frame, text="Monitor disabled", font=("Segoe UI", 8), foreground="gray"
        )
        self.monitor_status.pack(pady=(8, 0))

    def toggle_monitor(self):
        """Toggle resource monitoring on/off."""
        self._monitor_enabled = not self._monitor_enabled

        if self._monitor_enabled:
            self.btn_monitor_toggle.config(text="Disable Monitor")
            self.monitor_status.config(text="Monitoring active", foreground=self.colors["success"])
            self._update_resource_stats()
        else:
            self.btn_monitor_toggle.config(text="Enable Monitor")
            self.monitor_status.config(text="Monitor disabled", foreground="gray")
            if self._monitor_job:
                self.window.after_cancel(self._monitor_job)
                self._monitor_job = None
            # Reset labels
            self.cpu_label.config(text="--")
            self.mem_label.config(text="--")
            self.io_read_label.config(text="--")
            self.io_write_label.config(text="--")
            self.gpu_label.config(text="--")

    def _update_resource_stats(self):
        """Update resource statistics using container stats."""
        if not self._monitor_enabled:
            return
        if self._window_hidden:
            # Hidden in the tray: nothing to draw, check back later.
            self._monitor_job = self.window.after(15000, self._update_resource_stats)
            return

        try:
            # Get container configuration
            config = self._gather_config()
            runtime = config.get("runtime", "podman")
            container_name = "tlauncher"

            try:
                # Get container stats (one-shot, no stream)
                result = subprocess.run(
                    [
                        runtime,
                        "stats",
                        "--no-stream",
                        "--format",
                        "json" if runtime == "podman" else "table",
                        container_name,
                    ],
                    capture_output=True,
                    text=True,
                    timeout=3,
                )

                if result.returncode == 0 and result.stdout.strip():
                    output = result.stdout.strip()

                    if runtime == "podman":
                        # Podman outputs JSON array with one object

                        stats_list = json.loads(output)

                        # Get first (and only) container stats
                        if isinstance(stats_list, list) and len(stats_list) > 0:
                            stats = stats_list[0]
                        else:
                            stats = stats_list if isinstance(stats_list, dict) else {}

                        # CPU % (Podman uses 'cpu_percent' not 'CPU')
                        # Container stats show per-core usage, normalize to total system CPU
                        cpu_raw = stats.get("cpu_percent", "0%").replace("%", "")
                        try:
                            cpu_normalized = float(cpu_raw) / self._cpu_cores
                            cpu_cores = float(cpu_raw) / 100
                            self.cpu_label.config(
                                text=f"{cpu_normalized:.1f}%\n({cpu_cores:.1f} cores)"
                            )
                        except (ValueError, ZeroDivisionError):
                            self.cpu_label.config(text=f"{cpu_raw}%")

                        # Memory (Podman uses 'mem_usage' not 'MemUsage')
                        mem_usage = stats.get("mem_usage", "0B / 0B")
                        mem_parts = mem_usage.split("/")
                        if mem_parts:
                            self.mem_label.config(text=mem_parts[0].strip())

                        # Network I/O (Podman uses 'net_io' not 'NetIO')
                        net_io = stats.get("net_io", "0B / 0B")
                        net_parts = net_io.split("/")
                        if len(net_parts) == 2:
                            self.io_read_label.config(text=net_parts[0].strip())
                            self.io_write_label.config(text=net_parts[1].strip())

                    else:
                        # Docker outputs table format
                        # Parse the output line (skip header if present)
                        lines = output.split("\n")
                        data_line = lines[-1] if len(lines) > 0 else ""

                        # Format: CONTAINER ID   NAME   CPU %   MEM USAGE / LIMIT   MEM %   NET I/O   BLOCK I/O   PIDS
                        parts = re.split(r"\s{2,}", data_line.strip())

                        if len(parts) >= 3:
                            # CPU % (index 2)
                            # Container stats show per-core usage, normalize to total system CPU
                            cpu_raw = parts[2].replace("%", "")
                            try:
                                cpu_normalized = float(cpu_raw) / self._cpu_cores
                                cpu_cores = float(cpu_raw) / 100
                                self.cpu_label.config(
                                    text=f"{cpu_normalized:.1f}%\n({cpu_cores:.1f} cores)"
                                )
                            except (ValueError, ZeroDivisionError):
                                self.cpu_label.config(text=f"{cpu_raw}%")

                            # MEM USAGE (index 3)
                            if len(parts) >= 4:
                                mem_usage = parts[3].split("/")[0].strip()
                                self.mem_label.config(text=mem_usage)

                            # NET I/O (index 5)
                            if len(parts) >= 6:
                                net_io = parts[5]
                                net_parts = net_io.split("/")
                                if len(net_parts) == 2:
                                    self.io_read_label.config(text=net_parts[0].strip())
                                    self.io_write_label.config(text=net_parts[1].strip())

                    # GPU stats (NVIDIA only)
                    try:
                        if config.get("gpu") == "nvidia":
                            gpu_result = subprocess.run(
                                [
                                    "nvidia-smi",
                                    "--query-gpu=utilization.gpu",
                                    "--format=csv,noheader,nounits",
                                ],
                                capture_output=True,
                                text=True,
                                timeout=1,
                            )
                            if gpu_result.returncode == 0:
                                gpu_util = gpu_result.stdout.strip()
                                self.gpu_label.config(text=f"{gpu_util}%")
                            else:
                                self.gpu_label.config(text="--")
                        else:
                            self.gpu_label.config(text="N/A")
                    except (FileNotFoundError, subprocess.TimeoutExpired):
                        self.gpu_label.config(text="--")

                else:
                    # Container not running or not found
                    self._reset_monitor_labels()

            except (subprocess.TimeoutExpired, ValueError, json.JSONDecodeError):
                self._reset_monitor_labels()

        except Exception as e:
            self.log(f"Monitor error: {e}")

        # Schedule next update (2 seconds)
        if self._monitor_enabled:
            self._monitor_job = self.window.after(2000, self._update_resource_stats)

    def _reset_monitor_labels(self):
        """Reset monitor labels when container is not running."""
        self.cpu_label.config(text="--")
        self.mem_label.config(text="--")
        self.io_read_label.config(text="--")
        self.io_write_label.config(text="--")
        self.gpu_label.config(text="--")
