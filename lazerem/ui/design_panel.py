"""Design tools panel – material library, offset, array, nesting.

Provides a ``tk.ttk.Notebook`` with three tabs:
  * **Material Library** – quick-apply presets from the JSON library.
  * **Design Tools** – offset path, array/grid, boolean ops, nesting.
  * **Image Trace** – threshold, Floyd-Steinberg, Jarvis mode controls.
"""

from __future__ import annotations

from typing import Callable, List, Optional
import tkinter as tk
from tkinter import simpledialog, messagebox, ttk

from ..material_library import MaterialLibrary, MaterialPreset


_DARK_BG = "#0d1a0d"
_PANEL_BG = "#122012"
_LABEL_FG = "#7abf7a"
_VALUE_FG = "#00ff88"
_TITLE_FG = "#ccffcc"
_MONO_SM = ("Monospace", 9)
_BTN = dict(
    bg="#1a4a1a", fg="#ccffcc",
    activebackground="#2a6a2a", activeforeground="#ffffff",
    relief="flat", padx=6, pady=2,
    font=_MONO_SM, cursor="hand2",
)


class DesignPanel(tk.Frame):
    """Notebook panel containing Material Library, Design Tools, Image Trace."""

    def __init__(
        self,
        parent: tk.Widget,
        on_apply_material: Optional[Callable[[MaterialPreset], None]] = None,
        on_offset: Optional[Callable[[float], None]] = None,
        on_array: Optional[Callable[[int, int, float, float], None]] = None,
        on_nest: Optional[Callable[[float, float, float], None]] = None,
        on_trace: Optional[Callable[[str, float, float, float, float], None]] = None,
        **kwargs,
    ) -> None:
        kwargs.setdefault("bg", _DARK_BG)
        super().__init__(parent, **kwargs)

        self._on_apply_material = on_apply_material
        self._on_offset = on_offset
        self._on_array = on_array
        self._on_nest = on_nest
        self._on_trace = on_trace

        self._library = MaterialLibrary()

        nb = ttk.Notebook(self)
        nb.pack(fill="both", expand=True)

        self._build_material_tab(nb)
        self._build_tools_tab(nb)
        self._build_trace_tab(nb)

    # ------------------------------------------------------------------
    # Material Library tab
    # ------------------------------------------------------------------

    def _build_material_tab(self, nb: ttk.Notebook) -> None:
        frame = tk.Frame(nb, bg=_PANEL_BG)
        nb.add(frame, text="Materials")

        tk.Label(frame, text="MATERIAL LIBRARY", bg=_PANEL_BG, fg=_TITLE_FG,
                 font=_MONO_SM).pack(anchor="w", padx=6, pady=(6, 2))

        list_frame = tk.Frame(frame, bg=_PANEL_BG)
        list_frame.pack(fill="both", expand=True, padx=6, pady=(0, 4))

        sb = tk.Scrollbar(list_frame)
        sb.pack(side="right", fill="y")
        self._mat_listbox = tk.Listbox(
            list_frame,
            bg="#0a120a", fg="#99ff99",
            selectbackground="#1a4a1a",
            selectforeground="#ffffff",
            font=_MONO_SM,
            relief="flat",
            yscrollcommand=sb.set,
            height=8,
        )
        self._mat_listbox.pack(side="left", fill="both", expand=True)
        sb.config(command=self._mat_listbox.yview)
        self._mat_listbox.bind("<Double-1>", lambda _: self._apply_material())
        self._refresh_material_list()

        btn_frame = tk.Frame(frame, bg=_PANEL_BG)
        btn_frame.pack(fill="x", padx=6, pady=(0, 4))
        tk.Button(btn_frame, text="Apply", command=self._apply_material,
                  **_BTN).pack(side="left", padx=2)
        tk.Button(btn_frame, text="Add Current…", command=self._add_material,
                  **_BTN).pack(side="left", padx=2)
        tk.Button(btn_frame, text="Delete", command=self._delete_material,
                  **_BTN).pack(side="left", padx=2)

        # Detail display
        detail_frame = tk.Frame(frame, bg=_PANEL_BG)
        detail_frame.pack(fill="x", padx=6, pady=(0, 6))
        self._mat_detail = tk.StringVar(value="Select a preset to see details")
        tk.Label(detail_frame, textvariable=self._mat_detail,
                 bg=_PANEL_BG, fg=_VALUE_FG, font=_MONO_SM,
                 justify="left", anchor="w").pack(fill="x")
        self._mat_listbox.bind("<<ListboxSelect>>", self._on_mat_select)

    def _refresh_material_list(self) -> None:
        self._mat_listbox.delete(0, "end")
        for name in self._library.names():
            self._mat_listbox.insert("end", name)

    def _on_mat_select(self, _event=None) -> None:
        sel = self._mat_listbox.curselection()
        if not sel:
            return
        name = self._mat_listbox.get(sel[0])
        preset = self._library.get(name)
        if preset:
            self._mat_detail.set(
                f"Power: {preset.power:.0f}   Speed: {preset.speed:.0f} mm/min\n"
                f"Passes: {preset.passes}   Mode: {preset.mode}   "
                f"Dithering: {preset.dithering}"
            )

    def _apply_material(self) -> None:
        sel = self._mat_listbox.curselection()
        if not sel:
            return
        name = self._mat_listbox.get(sel[0])
        preset = self._library.get(name)
        if preset and callable(self._on_apply_material):
            self._on_apply_material(preset)

    def _add_material(self) -> None:
        name = simpledialog.askstring(
            "New Material", "Enter preset name:", parent=self
        )
        if not name or not name.strip():
            return
        # Ask the app to provide current settings via callback
        preset = MaterialPreset(name.strip())
        self._library.add(preset)
        self._library.save()
        self._refresh_material_list()

    def _delete_material(self) -> None:
        sel = self._mat_listbox.curselection()
        if not sel:
            return
        name = self._mat_listbox.get(sel[0])
        if messagebox.askyesno("Delete", f"Delete '{name}'?", parent=self):
            self._library.remove(name)
            self._library.save()
            self._refresh_material_list()
            self._mat_detail.set("")

    # ------------------------------------------------------------------
    # Design Tools tab
    # ------------------------------------------------------------------

    def _build_tools_tab(self, nb: ttk.Notebook) -> None:
        frame = tk.Frame(nb, bg=_PANEL_BG)
        nb.add(frame, text="Design")

        row = 0
        tk.Label(frame, text="DESIGN TOOLS", bg=_PANEL_BG, fg=_TITLE_FG,
                 font=_MONO_SM).grid(row=row, column=0, columnspan=3,
                                     sticky="w", padx=6, pady=(6, 4))
        row += 1

        # Offset
        tk.Label(frame, text="Path Offset (mm):", bg=_PANEL_BG, fg=_LABEL_FG,
                 font=_MONO_SM).grid(row=row, column=0, sticky="w", padx=6)
        self._offset_var = tk.StringVar(value="0.1")
        tk.Entry(frame, textvariable=self._offset_var,
                 width=7, bg="#071407", fg="#00ff88",
                 insertbackground="#00ff88", font=_MONO_SM,
                 relief="flat").grid(row=row, column=1, padx=4)
        tk.Button(frame, text="Apply", command=self._do_offset,
                  **_BTN).grid(row=row, column=2, padx=4)
        row += 1

        # Array
        tk.Label(frame, text="Array Grid:", bg=_PANEL_BG, fg=_LABEL_FG,
                 font=_MONO_SM).grid(row=row, column=0, sticky="w", padx=6, pady=(8, 0))
        row += 1

        labels_vals = [
            ("Cols", "arr_cols", "3"),
            ("Rows", "arr_rows", "3"),
            ("X gap (mm)", "arr_xsp", "50.0"),
            ("Y gap (mm)", "arr_ysp", "50.0"),
        ]
        self._arr_vars = {}
        for lbl, key, default in labels_vals:
            tk.Label(frame, text=f"  {lbl}:", bg=_PANEL_BG, fg=_LABEL_FG,
                     font=_MONO_SM).grid(row=row, column=0, sticky="w", padx=6)
            var = tk.StringVar(value=default)
            tk.Entry(frame, textvariable=var, width=7,
                     bg="#071407", fg="#00ff88",
                     insertbackground="#00ff88", font=_MONO_SM,
                     relief="flat").grid(row=row, column=1, padx=4)
            self._arr_vars[key] = var
            row += 1
        tk.Button(frame, text="Generate Array",
                  command=self._do_array, **_BTN).grid(
            row=row, column=0, columnspan=3, padx=6, pady=2, sticky="w")
        row += 1

        # Nesting
        tk.Label(frame, text="Nesting:", bg=_PANEL_BG, fg=_LABEL_FG,
                 font=_MONO_SM).grid(row=row, column=0, sticky="w", padx=6, pady=(8, 0))
        row += 1
        nest_labels = [
            ("Sheet W (mm)", "nest_w", "400.0"),
            ("Sheet H (mm)", "nest_h", "300.0"),
            ("Gap (mm)",     "nest_g", "2.0"),
        ]
        self._nest_vars = {}
        for lbl, key, default in nest_labels:
            tk.Label(frame, text=f"  {lbl}:", bg=_PANEL_BG, fg=_LABEL_FG,
                     font=_MONO_SM).grid(row=row, column=0, sticky="w", padx=6)
            var = tk.StringVar(value=default)
            tk.Entry(frame, textvariable=var, width=7,
                     bg="#071407", fg="#00ff88",
                     insertbackground="#00ff88", font=_MONO_SM,
                     relief="flat").grid(row=row, column=1, padx=4)
            self._nest_vars[key] = var
            row += 1
        tk.Button(frame, text="Auto-Nest", command=self._do_nest,
                  **_BTN).grid(row=row, column=0, columnspan=3,
                                padx=6, pady=2, sticky="w")

    def _do_offset(self) -> None:
        try:
            dist = float(self._offset_var.get())
        except ValueError:
            messagebox.showerror("Error", "Invalid offset distance.", parent=self)
            return
        if callable(self._on_offset):
            self._on_offset(dist)

    def _do_array(self) -> None:
        try:
            cols = int(self._arr_vars["arr_cols"].get())
            rows = int(self._arr_vars["arr_rows"].get())
            xsp = float(self._arr_vars["arr_xsp"].get())
            ysp = float(self._arr_vars["arr_ysp"].get())
        except ValueError:
            messagebox.showerror("Error", "Invalid array parameters.", parent=self)
            return
        if callable(self._on_array):
            self._on_array(cols, rows, xsp, ysp)

    def _do_nest(self) -> None:
        try:
            w = float(self._nest_vars["nest_w"].get())
            h = float(self._nest_vars["nest_h"].get())
            g = float(self._nest_vars["nest_g"].get())
        except ValueError:
            messagebox.showerror("Error", "Invalid nesting parameters.", parent=self)
            return
        if callable(self._on_nest):
            self._on_nest(w, h, g)

    # ------------------------------------------------------------------
    # Image Trace tab
    # ------------------------------------------------------------------

    def _build_trace_tab(self, nb: ttk.Notebook) -> None:
        frame = tk.Frame(nb, bg=_PANEL_BG)
        nb.add(frame, text="Trace")

        tk.Label(frame, text="IMAGE TRACE", bg=_PANEL_BG, fg=_TITLE_FG,
                 font=_MONO_SM).pack(anchor="w", padx=6, pady=(6, 4))

        grid = tk.Frame(frame, bg=_PANEL_BG)
        grid.pack(fill="x", padx=6)

        row = 0
        tk.Label(grid, text="Mode:", bg=_PANEL_BG, fg=_LABEL_FG,
                 font=_MONO_SM).grid(row=row, column=0, sticky="w")
        self._trace_mode = tk.StringVar(value="threshold")
        ttk.Combobox(grid, textvariable=self._trace_mode,
                     values=["threshold", "floyd-steinberg", "jarvis"],
                     state="readonly", width=14).grid(row=row, column=1, sticky="w", padx=4)
        row += 1

        tk.Label(grid, text="Threshold:", bg=_PANEL_BG, fg=_LABEL_FG,
                 font=_MONO_SM).grid(row=row, column=0, sticky="w", pady=2)
        self._trace_thresh = tk.StringVar(value="0.5")
        tk.Entry(grid, textvariable=self._trace_thresh, width=6,
                 bg="#071407", fg="#00ff88", insertbackground="#00ff88",
                 font=_MONO_SM, relief="flat").grid(row=row, column=1, sticky="w", padx=4)
        row += 1

        tk.Label(grid, text="Pixel (mm):", bg=_PANEL_BG, fg=_LABEL_FG,
                 font=_MONO_SM).grid(row=row, column=0, sticky="w", pady=2)
        self._trace_px = tk.StringVar(value="0.1")
        tk.Entry(grid, textvariable=self._trace_px, width=6,
                 bg="#071407", fg="#00ff88", insertbackground="#00ff88",
                 font=_MONO_SM, relief="flat").grid(row=row, column=1, sticky="w", padx=4)
        row += 1

        tk.Label(grid, text="Power (S):", bg=_PANEL_BG, fg=_LABEL_FG,
                 font=_MONO_SM).grid(row=row, column=0, sticky="w", pady=2)
        self._trace_power = tk.StringVar(value="500")
        tk.Entry(grid, textvariable=self._trace_power, width=6,
                 bg="#071407", fg="#00ff88", insertbackground="#00ff88",
                 font=_MONO_SM, relief="flat").grid(row=row, column=1, sticky="w", padx=4)
        row += 1

        tk.Label(grid, text="Speed (F):", bg=_PANEL_BG, fg=_LABEL_FG,
                 font=_MONO_SM).grid(row=row, column=0, sticky="w", pady=2)
        self._trace_speed = tk.StringVar(value="3000")
        tk.Entry(grid, textvariable=self._trace_speed, width=6,
                 bg="#071407", fg="#00ff88", insertbackground="#00ff88",
                 font=_MONO_SM, relief="flat").grid(row=row, column=1, sticky="w", padx=4)
        row += 1

        tk.Button(frame, text="Trace Image…",
                  command=self._do_trace, **_BTN).pack(anchor="w", padx=6, pady=6)

    def _do_trace(self) -> None:
        try:
            thresh = float(self._trace_thresh.get())
            px = float(self._trace_px.get())
            power = float(self._trace_power.get())
            speed = float(self._trace_speed.get())
        except ValueError:
            messagebox.showerror("Error", "Invalid trace parameters.", parent=self)
            return
        mode = self._trace_mode.get()
        if callable(self._on_trace):
            self._on_trace(mode, thresh, px, power, speed)

    # ------------------------------------------------------------------
    # Public helpers
    # ------------------------------------------------------------------

    def refresh_library(self) -> None:
        """Reload the material list (call after external changes)."""
        self._library = MaterialLibrary()
        self._refresh_material_list()
