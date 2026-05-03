"""Status and coordinate display panels for the Ray5W laser control."""

from __future__ import annotations

import tkinter as tk

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
