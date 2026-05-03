"""Layers panel for the Ray5W laser control drawing module.

Provides :class:`LayersPanel` – a ``tk.Frame`` that lets the user:

* View all layers in a list with their colour swatch.
* Add, delete, and duplicate layers.
* Edit the selected layer's name, colour (hex), power, speed, *enabled* flag,
  and *no_cut* flag.
* Notify a callback whenever the layer list changes so the canvas can redraw.
"""

from __future__ import annotations

import tkinter as tk
from tkinter import ttk
from typing import Callable, List, Optional

from ..drawing import DrawingDocument, Layer


_DARK_BG = "#0d1a0d"
_PANEL_BG = "#0a120a"
_LABEL_FG = "#7abf7a"
_VALUE_FG = "#00ff88"
_TITLE_FG = "#ccffcc"
_MONO_SM = ("Monospace", 9)
_ENTRY = dict(bg="#071407", fg="#00ff88", insertbackground="#00ff88",
              font=_MONO_SM, relief="flat")
_BTN = dict(
    bg="#1a4a1a", fg="#ccffcc",
    activebackground="#2a6a2a", activeforeground="#ffffff",
    relief="flat", padx=6, pady=2,
    font=_MONO_SM, cursor="hand2",
)

_PRESET_COLORS = [
    "#00ff88",   # green  – default cut
    "#ff4444",   # red    – engrave
    "#4488ff",   # blue   – score
    "#ffaa00",   # orange – mark
    "#ff88ff",   # pink
    "#88ffff",   # cyan
    "#ffffff",   # white
    "#888888",   # grey   – reference / no-cut
]


class LayersPanel(tk.Frame):
    """Panel for managing drawing layers.

    Parameters
    ----------
    parent:
        Parent widget.
    doc:
        The shared :class:`~lazerem.drawing.DrawingDocument`.
    on_change:
        Called (with no arguments) whenever layers are modified so the
        caller can trigger a canvas redraw.
    on_active_change:
        Called with the new active layer index whenever the selected layer
        changes.
    """

    def __init__(
        self,
        parent: tk.Widget,
        doc: DrawingDocument,
        on_change: Optional[Callable[[], None]] = None,
        on_active_change: Optional[Callable[[int], None]] = None,
    ) -> None:
        super().__init__(parent, bg=_DARK_BG)
        self._doc = doc
        self._on_change = on_change
        self._on_active_change = on_active_change
        self._selected: int = 0

        self._build_ui()
        self._refresh_list()

    # ------------------------------------------------------------------
    # UI construction
    # ------------------------------------------------------------------

    def _build_ui(self) -> None:
        tk.Label(self, text="LAYERS", bg=_DARK_BG, fg=_TITLE_FG,
                 font=("Monospace", 9, "bold")).pack(anchor="w",
                                                     padx=4, pady=(4, 2))

        # --- Layer list ---
        list_frame = tk.Frame(self, bg=_DARK_BG)
        list_frame.pack(fill="both", expand=True, padx=4, pady=(0, 2))

        sb = tk.Scrollbar(list_frame, orient="vertical")
        sb.pack(side="right", fill="y")

        self._listbox = tk.Listbox(
            list_frame, bg=_PANEL_BG, fg=_VALUE_FG,
            selectbackground="#1a4a1a", selectforeground="#ffffff",
            font=_MONO_SM, relief="flat", height=6,
            yscrollcommand=sb.set,
        )
        self._listbox.pack(side="left", fill="both", expand=True)
        sb.config(command=self._listbox.yview)
        self._listbox.bind("<<ListboxSelect>>", self._on_list_select)

        # --- Buttons ---
        btn_row = tk.Frame(self, bg=_DARK_BG)
        btn_row.pack(fill="x", padx=4, pady=(0, 4))

        tk.Button(btn_row, text="+", command=self._add_layer,
                  **_BTN).pack(side="left", padx=2)
        tk.Button(btn_row, text="✕", command=self._delete_layer,
                  bg="#4a1a1a", fg="#ffcccc",
                  activebackground="#6a2a2a", activeforeground="#ffffff",
                  relief="flat", padx=6, pady=2,
                  font=_MONO_SM, cursor="hand2").pack(side="left", padx=2)
        tk.Button(btn_row, text="⧉", command=self._duplicate_layer,
                  **_BTN).pack(side="left", padx=2)
        tk.Button(btn_row, text="▲", command=self._move_up,
                  **_BTN).pack(side="left", padx=2)
        tk.Button(btn_row, text="▼", command=self._move_down,
                  **_BTN).pack(side="left", padx=2)

        # --- Property editor ---
        sep = tk.Frame(self, bg="#1a3a1a", height=1)
        sep.pack(fill="x", padx=4, pady=2)

        editor = tk.Frame(self, bg=_DARK_BG)
        editor.pack(fill="x", padx=4, pady=(0, 4))

        row = 0

        def _lbl(text, r):
            tk.Label(editor, text=text, bg=_DARK_BG, fg=_LABEL_FG,
                     font=_MONO_SM).grid(row=r, column=0, sticky="w", pady=1)

        _lbl("Name:", row)
        self._name_var = tk.StringVar()
        name_entry = tk.Entry(editor, textvariable=self._name_var, width=14,
                              **_ENTRY)
        name_entry.grid(row=row, column=1, columnspan=2, sticky="ew", padx=(4, 0))
        name_entry.bind("<FocusOut>", lambda _: self._apply_edits())
        name_entry.bind("<Return>", lambda _: self._apply_edits())
        row += 1

        _lbl("Colour:", row)
        self._color_var = tk.StringVar()
        self._color_swatch = tk.Label(
            editor, text="  ", bg="#00ff88", relief="flat", width=2)
        self._color_swatch.grid(row=row, column=1, sticky="w", padx=(4, 2))
        color_entry = tk.Entry(editor, textvariable=self._color_var, width=9,
                               **_ENTRY)
        color_entry.grid(row=row, column=2, sticky="ew")
        color_entry.bind("<FocusOut>", lambda _: self._apply_edits())
        color_entry.bind("<Return>", lambda _: self._apply_edits())
        row += 1

        # Colour presets
        preset_frame = tk.Frame(editor, bg=_DARK_BG)
        preset_frame.grid(row=row, column=0, columnspan=3, sticky="w",
                          pady=(0, 2))
        for pc in _PRESET_COLORS:
            tk.Button(
                preset_frame, text=" ", bg=pc, width=1, height=1,
                relief="flat", cursor="hand2",
                command=lambda c=pc: self._pick_color(c),
            ).pack(side="left", padx=1)
        row += 1

        _lbl("Power (S):", row)
        self._power_var = tk.StringVar()
        tk.Entry(editor, textvariable=self._power_var, width=6,
                 **_ENTRY).grid(row=row, column=1, columnspan=2, sticky="w",
                                padx=(4, 0))
        row += 1

        _lbl("Speed (F):", row)
        self._speed_var = tk.StringVar()
        tk.Entry(editor, textvariable=self._speed_var, width=7,
                 **_ENTRY).grid(row=row, column=1, columnspan=2, sticky="w",
                                padx=(4, 0))
        row += 1

        self._enabled_var = tk.BooleanVar(value=True)
        tk.Checkbutton(
            editor, text="Enabled (visible)", variable=self._enabled_var,
            bg=_DARK_BG, fg=_LABEL_FG, selectcolor="#0a120a",
            activebackground=_DARK_BG, font=_MONO_SM,
            command=self._apply_edits,
        ).grid(row=row, column=0, columnspan=3, sticky="w")
        row += 1

        self._nocut_var = tk.BooleanVar(value=False)
        tk.Checkbutton(
            editor, text="No Cut  (stock / material only)",
            variable=self._nocut_var,
            bg=_DARK_BG, fg="#ff8888", selectcolor="#0a120a",
            activebackground=_DARK_BG, font=_MONO_SM,
            command=self._apply_edits,
        ).grid(row=row, column=0, columnspan=3, sticky="w")
        row += 1

        tk.Button(editor, text="Apply", command=self._apply_edits,
                  **_BTN).grid(row=row, column=0, columnspan=3,
                               sticky="w", pady=(4, 0))

        editor.columnconfigure(2, weight=1)

    # ------------------------------------------------------------------
    # List management
    # ------------------------------------------------------------------

    def _refresh_list(self) -> None:
        self._listbox.delete(0, "end")
        for i, layer in enumerate(self._doc.layers):
            tag = "●"
            status = "[no-cut]" if layer.no_cut else ""
            disabled = "" if layer.enabled else "(off)"
            entry = f" {tag} {layer.name}  {status}{disabled}"
            self._listbox.insert("end", entry)
            # Colour the swatch indicator
            try:
                self._listbox.itemconfig(i, fg=layer.color)
            except Exception:
                pass
        # Keep selection
        if self._doc.layers:
            sel = min(self._selected, len(self._doc.layers) - 1)
            self._listbox.selection_clear(0, "end")
            self._listbox.selection_set(sel)
            self._listbox.see(sel)
            self._load_layer(sel)

    def _on_list_select(self, _event=None) -> None:
        sel = self._listbox.curselection()
        if not sel:
            return
        idx = int(sel[0])
        self._selected = idx
        self._load_layer(idx)
        if self._on_active_change:
            self._on_active_change(idx)

    def _load_layer(self, idx: int) -> None:
        if 0 <= idx < len(self._doc.layers):
            layer = self._doc.layers[idx]
            self._name_var.set(layer.name)
            self._color_var.set(layer.color)
            self._power_var.set(str(int(layer.power)))
            self._speed_var.set(str(int(layer.speed)))
            self._enabled_var.set(layer.enabled)
            self._nocut_var.set(layer.no_cut)
            try:
                self._color_swatch.config(bg=layer.color)
            except Exception:
                pass

    def _apply_edits(self) -> None:
        idx = self._selected
        if not (0 <= idx < len(self._doc.layers)):
            return
        layer = self._doc.layers[idx]
        layer.name = self._name_var.get().strip() or layer.name
        color = self._color_var.get().strip()
        if color.startswith("#") and len(color) in (4, 7):
            layer.color = color
            try:
                self._color_swatch.config(bg=color)
            except Exception:
                pass
        try:
            layer.power = max(0.0, min(1000.0, float(self._power_var.get())))
        except ValueError:
            pass
        try:
            layer.speed = max(1.0, float(self._speed_var.get()))
        except ValueError:
            pass
        layer.enabled = self._enabled_var.get()
        layer.no_cut = self._nocut_var.get()
        self._refresh_list()
        self._notify()

    def _pick_color(self, color: str) -> None:
        self._color_var.set(color)
        self._apply_edits()

    def _add_layer(self) -> None:
        n = len(self._doc.layers) + 1
        self._doc.add_layer(f"Layer {n}")
        self._selected = len(self._doc.layers) - 1
        self._refresh_list()
        self._notify()

    def _delete_layer(self) -> None:
        idx = self._selected
        if len(self._doc.layers) <= 1:
            return  # keep at least one layer
        self._doc.remove_layer(idx)
        self._selected = max(0, idx - 1)
        self._refresh_list()
        self._notify()

    def _duplicate_layer(self) -> None:
        idx = self._selected
        if not (0 <= idx < len(self._doc.layers)):
            return
        src = self._doc.layers[idx]
        new = Layer(
            name=src.name + " copy",
            color=src.color,
            power=src.power,
            speed=src.speed,
            enabled=src.enabled,
            no_cut=src.no_cut,
        )
        self._doc.layers.insert(idx + 1, new)
        self._selected = idx + 1
        self._refresh_list()
        self._notify()

    def _move_up(self) -> None:
        idx = self._selected
        if idx <= 0:
            return
        layers = self._doc.layers
        layers[idx - 1], layers[idx] = layers[idx], layers[idx - 1]
        # Remap object layer indices
        for obj in self._doc.objects:
            if obj.layer_idx == idx:
                obj.layer_idx = idx - 1
            elif obj.layer_idx == idx - 1:
                obj.layer_idx = idx
        self._selected = idx - 1
        self._refresh_list()
        self._notify()

    def _move_down(self) -> None:
        idx = self._selected
        layers = self._doc.layers
        if idx >= len(layers) - 1:
            return
        layers[idx + 1], layers[idx] = layers[idx], layers[idx + 1]
        for obj in self._doc.objects:
            if obj.layer_idx == idx:
                obj.layer_idx = idx + 1
            elif obj.layer_idx == idx + 1:
                obj.layer_idx = idx
        self._selected = idx + 1
        self._refresh_list()
        self._notify()

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _notify(self) -> None:
        if self._on_change:
            self._on_change()

    def set_document(self, doc: DrawingDocument) -> None:
        self._doc = doc
        self._selected = 0
        self._refresh_list()

    @property
    def selected_index(self) -> int:
        return self._selected
