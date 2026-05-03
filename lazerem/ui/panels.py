"""Status and coordinate display panels for the Ray5W laser control."""

from __future__ import annotations

from typing import Optional
import tkinter as tk
from tkinter import ttk

from ..machine import LaserMachine


_DARK_BG = "#0d1a0d"
_PANEL_BG = "#122012"
_LABEL_FG = "#7abf7a"
_VALUE_FG = "#00ff88"
_ALARM_FG = "#ff4444"
_TITLE_FG = "#ccffcc"

_MONO = ("Monospace", 10)
_MONO_LG = ("Monospace", 14, "bold")
_MONO_SM = ("Monospace", 9)


class CoordinatePanel(tk.Frame):
    """Shows current machine position (X Y)."""

    def __init__(self, parent: tk.Widget, **kwargs) -> None:
        kwargs.setdefault("bg", _PANEL_BG)
        kwargs.setdefault("padx", 8)
        kwargs.setdefault("pady", 8)
        super().__init__(parent, **kwargs)

        tk.Label(self, text="POSITION", bg=_PANEL_BG, fg=_TITLE_FG,
                 font=_MONO_SM).grid(row=0, column=0, columnspan=2,
                                     sticky="w", pady=(0, 4))

        self._vars = {}
        for row, axis in enumerate(("X", "Y"), start=1):
            tk.Label(self, text=f" {axis} ", bg=_PANEL_BG, fg=_LABEL_FG,
                     font=_MONO_LG).grid(row=row, column=0, sticky="w")
            var = tk.StringVar(value="   0.000")
            tk.Label(self, textvariable=var, bg=_PANEL_BG, fg=_VALUE_FG,
                     font=_MONO_LG, width=12, anchor="e").grid(
                row=row, column=1, sticky="e", padx=(4, 0))
            self._vars[axis] = var

    def update_from(self, machine: LaserMachine) -> None:
        self._vars["X"].set(f"{machine.position.x:>10.3f}")
        self._vars["Y"].set(f"{machine.position.y:>10.3f}")


class LaserStatusPanel(tk.Frame):
    """Shows laser power, mode, feed rate, and overall status."""

    def __init__(self, parent: tk.Widget, **kwargs) -> None:
        kwargs.setdefault("bg", _PANEL_BG)
        kwargs.setdefault("padx", 8)
        kwargs.setdefault("pady", 8)
        super().__init__(parent, **kwargs)

        tk.Label(self, text="LASER STATUS", bg=_PANEL_BG, fg=_TITLE_FG,
                 font=_MONO_SM).grid(row=0, column=0, columnspan=2,
                                     sticky="w", pady=(0, 4))

        rows = [
            ("STATUS", "status"),
            ("LASER",  "laser"),
            ("POWER",  "power"),
            ("FEED",   "feed"),
            ("UNITS",  "units"),
            ("MODE",   "mode"),
        ]
        self._vars = {}
        for i, (label, key) in enumerate(rows, start=1):
            tk.Label(self, text=f"{label}:", bg=_PANEL_BG, fg=_LABEL_FG,
                     font=_MONO_SM, anchor="w", width=9).grid(
                row=i, column=0, sticky="w")
            var = tk.StringVar(value="—")
            color = _ALARM_FG if key == "status" else _VALUE_FG
            tk.Label(self, textvariable=var, bg=_PANEL_BG, fg=color,
                     font=_MONO, anchor="w").grid(row=i, column=1, sticky="w")
            self._vars[key] = var

    def update_from(self, machine: LaserMachine) -> None:
        self._vars["status"].set(machine.status)

        if machine.laser_on:
            mode_str = "DYNAMIC" if machine.laser_dynamic else "CONSTANT"
            self._vars["laser"].set(f"ON  ({mode_str})")
        else:
            self._vars["laser"].set("OFF")

        pct = machine.laser_power / machine.MAX_POWER * 100
        self._vars["power"].set(
            f"{machine.laser_power:.0f} / {machine.MAX_POWER:.0f}"
            f"  ({pct:.1f} %)"
        )
        self._vars["feed"].set(f"{machine.feed_rate:.0f} mm/min")
        self._vars["units"].set("Metric (mm)" if machine.units == 21 else "Inch")
        self._vars["mode"].set(
            "ABSOLUTE" if machine.distance_mode == 90 else "INCREMENTAL"
        )


class AdvancedSettingsPanel(tk.Frame):
    """Shows and edits pass count, dithering mode, and controller type."""

    _DITHERING_OPTIONS = ["none", "threshold", "floyd-steinberg", "jarvis"]
    _CONTROLLER_OPTIONS = ["GRBL", "Marlin", "Ruida"]

    def __init__(self, parent: tk.Widget,
                 on_change: Optional[object] = None, **kwargs) -> None:
        kwargs.setdefault("bg", _PANEL_BG)
        kwargs.setdefault("padx", 8)
        kwargs.setdefault("pady", 8)
        super().__init__(parent, **kwargs)
        self._on_change = on_change

        tk.Label(self, text="ADVANCED SETTINGS", bg=_PANEL_BG, fg=_TITLE_FG,
                 font=_MONO_SM).grid(row=0, column=0, columnspan=2,
                                     sticky="w", pady=(0, 4))

        # Pass count
        tk.Label(self, text="PASSES:", bg=_PANEL_BG, fg=_LABEL_FG,
                 font=_MONO_SM, anchor="w", width=12).grid(row=1, column=0, sticky="w")
        self._pass_var = tk.IntVar(value=1)
        ttk.Spinbox(self, from_=1, to=99, textvariable=self._pass_var,
                    width=5, command=self._notify).grid(row=1, column=1, sticky="w")

        # Dithering
        tk.Label(self, text="DITHERING:", bg=_PANEL_BG, fg=_LABEL_FG,
                 font=_MONO_SM, anchor="w", width=12).grid(row=2, column=0, sticky="w")
        self._dither_var = tk.StringVar(value="none")
        dither_cb = ttk.Combobox(self, textvariable=self._dither_var,
                                  values=self._DITHERING_OPTIONS,
                                  state="readonly", width=14)
        dither_cb.grid(row=2, column=1, sticky="w")
        dither_cb.bind("<<ComboboxSelected>>", lambda _: self._notify())

        # Controller
        tk.Label(self, text="CONTROLLER:", bg=_PANEL_BG, fg=_LABEL_FG,
                 font=_MONO_SM, anchor="w", width=12).grid(row=3, column=0, sticky="w")
        self._ctrl_var = tk.StringVar(value="GRBL")
        ctrl_cb = ttk.Combobox(self, textvariable=self._ctrl_var,
                                values=self._CONTROLLER_OPTIONS,
                                state="readonly", width=14)
        ctrl_cb.grid(row=3, column=1, sticky="w")
        ctrl_cb.bind("<<ComboboxSelected>>", lambda _: self._notify())

    def _notify(self) -> None:
        if callable(self._on_change):
            self._on_change()

    @property
    def pass_count(self) -> int:
        return max(1, self._pass_var.get())

    @property
    def dithering_mode(self) -> str:
        return self._dither_var.get()

    @property
    def controller_type(self) -> str:
        return self._ctrl_var.get()

    def update_from(self, machine: LaserMachine) -> None:
        self._pass_var.set(machine.pass_count)
        self._dither_var.set(machine.dithering_mode)
        self._ctrl_var.set(machine.controller_type)


class MessageLog(tk.Frame):
    """Scrollable log of execution messages."""

    def __init__(self, parent: tk.Widget, **kwargs) -> None:
        kwargs.setdefault("bg", _PANEL_BG)
        super().__init__(parent, **kwargs)

        tk.Label(self, text="MESSAGE LOG", bg=_PANEL_BG, fg=_TITLE_FG,
                 font=_MONO_SM).pack(anchor="w", padx=6, pady=(6, 2))

        frame = tk.Frame(self, bg=_PANEL_BG)
        frame.pack(fill="both", expand=True, padx=6, pady=(0, 6))

        scrollbar = tk.Scrollbar(frame)
        scrollbar.pack(side="right", fill="y")

        self._text = tk.Text(
            frame,
            height=6,
            bg="#0a120a",
            fg="#99cc99",
            font=_MONO_SM,
            relief="flat",
            state="disabled",
            yscrollcommand=scrollbar.set,
        )
        self._text.pack(side="left", fill="both", expand=True)
        scrollbar.config(command=self._text.yview)

    def log(self, message: str) -> None:
        self._text.config(state="normal")
        self._text.insert("end", message + "\n")
        self._text.see("end")
        self._text.config(state="disabled")

    def clear(self) -> None:
        self._text.config(state="normal")
        self._text.delete("1.0", "end")
        self._text.config(state="disabled")
