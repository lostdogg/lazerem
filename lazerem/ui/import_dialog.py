"""Import parameters dialog for the Ray5W laser control.

Shows a modal window whenever a file is imported (SVG, DXF, or raster image)
so the user can configure:

* Physical output size (width/height in mm)
* X/Y origin offset (translate the imported design)
* Toolpath type (Line, Fill/Raster, Hatch, Dithered, Greyscale, etc.)
* Type-specific options (line spacing, angle, dithering algorithm, etc.)
* Power (S) and speed (F)
* A live preview canvas showing the design being imported
"""

from __future__ import annotations

import math
from typing import Dict, List, Optional, Tuple
import tkinter as tk
from tkinter import ttk


_DARK_BG = "#0d1a0d"
_PANEL_BG = "#122012"
_LABEL_FG = "#7abf7a"
_VALUE_FG = "#00ff88"
_TITLE_FG = "#ccffcc"
_MONO_SM = ("Monospace", 9)
_ENTRY = dict(bg="#071407", fg="#00ff88", insertbackground="#00ff88",
              font=_MONO_SM, relief="flat")
_BTN = dict(
    bg="#1a4a1a", fg="#ccffcc",
    activebackground="#2a6a2a", activeforeground="#ffffff",
    relief="flat", padx=8, pady=3,
    font=_MONO_SM, cursor="hand2",
)

# Toolpath types available for vector imports (SVG / DXF)
VECTOR_TOOLPATH_TYPES = [
    "Line (Cut)",
    "Fill (Raster Engraving)",
    "Offset Fill",
    "Hatch Fill",
    "Perforation (Dash/Score)",
    "Greyscale (Variable Power)",
    "Knife/Drag",
    "Optimization",
    "Spiral Toolpath",
]

# Toolpath types available for raster image imports
IMAGE_TOOLPATH_TYPES = [
    "Fill (Raster Engraving)",
    "Image (Floyd-Steinberg Dither)",
    "Image (Jarvis Dither)",
    "Greyscale (Variable Power)",
    "Hatch Fill",
]

# Preview canvas dimensions
_PREV_W = 220
_PREV_H = 180
_PREV_BG = "#071407"
_PREV_LINE = "#00cc66"
_PREV_GRID = "#0f2a0f"


class ImportParamsDialog(tk.Toplevel):
    """Modal dialog for configuring import parameters.

    Parameters
    ----------
    parent:
        Parent tkinter widget.
    import_type:
        One of ``'svg'``, ``'dxf'``, or ``'image'``.
    filename:
        Base name shown in the title bar.
    img_w, img_h:
        Pixel dimensions of the source image (used only for ``import_type='image'``).
    default_power:
        Initial laser power (S value).
    default_speed:
        Initial feed rate (mm/min).
    preview_paths:
        Optional list of point lists ``[(x, y), …]`` to render as a preview
        (used for SVG / DXF imports).
    preview_grid:
        Optional 2-D list of grayscale float values (0–1) for image previews.

    After the dialog closes, inspect :attr:`result`.  It is ``None`` if the
    user cancelled, or a ``dict`` with these keys:

    * ``toolpath_type`` – str
    * ``width_mm`` – float (0 = keep original scale)
    * ``height_mm`` – float (0 = keep original scale / computed)
    * ``lock_ratio`` – bool
    * ``origin_x`` – float (X translation offset in mm)
    * ``origin_y`` – float (Y translation offset in mm)
    * ``power`` – float
    * ``speed`` – float
    * ``line_spacing`` – float  (Fill/Raster, Hatch)
    * ``angle`` – float         (Hatch)
    * ``crosshatch`` – bool     (Hatch)
    * ``dithering_mode`` – str  (Dithered variants)
    * ``threshold`` – float     (Dithered, Greyscale, Fill/Raster)
    * ``offset_dist`` – float   (Offset Fill)
    * ``offset_count`` – int    (Offset Fill)
    * ``dash_mm`` – float       (Perforation)
    * ``gap_mm`` – float        (Perforation)
    * ``blade_offset`` – float  (Knife/Drag)
    * ``spiral_r_start`` – float (Spiral)
    * ``spiral_r_end`` – float  (Spiral)
    * ``spiral_spacing`` – float (Spiral)
    """

    def __init__(
        self,
        parent: tk.Widget,
        import_type: str = "svg",
        filename: str = "",
        img_w: int = 0,
        img_h: int = 0,
        default_power: float = 500.0,
        default_speed: float = 3000.0,
        preview_paths: Optional[List[List[Tuple[float, float]]]] = None,
        preview_grid: Optional[List[List[float]]] = None,
    ) -> None:
        super().__init__(parent)

        self.result: Optional[Dict] = None
        self._import_type = import_type.lower()
        self._img_w = img_w
        self._img_h = img_h
        self._aspect: float = img_w / img_h if (img_w and img_h) else 1.0
        self._preview_paths = preview_paths
        self._preview_grid = preview_grid

        label = filename or import_type.upper()
        self.title(f"Import Parameters – {label}")
        self.configure(bg=_DARK_BG)
        self.resizable(True, True)

        self._build_ui(default_power, default_speed)

        self.transient(parent)
        self.grab_set()
        self.wait_window()

    # ------------------------------------------------------------------
    # UI construction
    # ------------------------------------------------------------------

    def _build_ui(self, default_power: float, default_speed: float) -> None:
        # Top-level split: left = controls, right = preview
        main_frame = tk.Frame(self, bg=_DARK_BG)
        main_frame.pack(fill="both", expand=True, padx=4, pady=4)

        outer = tk.Frame(main_frame, bg=_DARK_BG, padx=14, pady=10)
        outer.pack(side="left", fill="both")

        # --- Preview panel (right side) ---
        prev_frame = tk.Frame(main_frame, bg=_DARK_BG, padx=6, pady=10)
        prev_frame.pack(side="left", fill="both", expand=True)
        tk.Label(
            prev_frame, text="PREVIEW", bg=_DARK_BG, fg=_LABEL_FG,
            font=_MONO_SM,
        ).pack(anchor="w")
        self._prev_canvas = tk.Canvas(
            prev_frame,
            width=_PREV_W, height=_PREV_H,
            bg=_PREV_BG, highlightthickness=1,
            highlightbackground="#1a4a1a",
        )
        self._prev_canvas.pack(fill="both", expand=True)

        row = 0

        # --- Title ---
        tk.Label(
            outer, text="IMPORT PARAMETERS", bg=_DARK_BG, fg=_TITLE_FG,
            font=("Monospace", 10, "bold"),
        ).grid(row=row, column=0, columnspan=3, sticky="w", pady=(0, 8))
        row += 1

        # --- Physical size ---
        tk.Label(outer, text="Output Size (mm)", bg=_DARK_BG, fg=_TITLE_FG,
                 font=_MONO_SM).grid(row=row, column=0, columnspan=3,
                                     sticky="w", pady=(0, 2))
        row += 1

        tk.Label(outer, text="Width:", bg=_DARK_BG, fg=_LABEL_FG,
                 font=_MONO_SM).grid(row=row, column=0, sticky="w")
        self._width_var = tk.StringVar(value="0")
        tk.Entry(outer, textvariable=self._width_var, width=8,
                 **_ENTRY).grid(row=row, column=1, sticky="w", padx=(4, 2))
        tk.Label(outer, text="mm  (0 = native size)", bg=_DARK_BG,
                 fg=_LABEL_FG, font=_MONO_SM).grid(row=row, column=2, sticky="w")
        row += 1

        tk.Label(outer, text="Height:", bg=_DARK_BG, fg=_LABEL_FG,
                 font=_MONO_SM).grid(row=row, column=0, sticky="w")
        self._height_var = tk.StringVar(value="0")
        tk.Entry(outer, textvariable=self._height_var, width=8,
                 **_ENTRY).grid(row=row, column=1, sticky="w", padx=(4, 2))
        tk.Label(outer, text="mm  (0 = keep ratio)", bg=_DARK_BG,
                 fg=_LABEL_FG, font=_MONO_SM).grid(row=row, column=2, sticky="w")
        row += 1

        self._lock_ratio_var = tk.BooleanVar(value=True)
        tk.Checkbutton(
            outer, text="Lock aspect ratio", variable=self._lock_ratio_var,
            bg=_DARK_BG, fg=_LABEL_FG, selectcolor="#0a120a",
            activebackground=_DARK_BG, font=_MONO_SM,
        ).grid(row=row, column=0, columnspan=3, sticky="w", pady=(0, 4))
        self._width_var.trace_add("write", self._on_width_change)
        row += 1

        # Separator
        tk.Frame(outer, bg="#1a3a1a", height=1).grid(
            row=row, column=0, columnspan=3, sticky="ew", pady=6)
        row += 1

        # --- Origin offset (translate) ---
        tk.Label(outer, text="Origin Offset (mm)", bg=_DARK_BG, fg=_TITLE_FG,
                 font=_MONO_SM).grid(row=row, column=0, columnspan=3,
                                     sticky="w", pady=(0, 2))
        row += 1

        tk.Label(outer, text="X offset:", bg=_DARK_BG, fg=_LABEL_FG,
                 font=_MONO_SM).grid(row=row, column=0, sticky="w")
        self._origin_x_var = tk.StringVar(value="0")
        tk.Entry(outer, textvariable=self._origin_x_var, width=8,
                 **_ENTRY).grid(row=row, column=1, sticky="w", padx=(4, 2))
        tk.Label(outer, text="mm", bg=_DARK_BG, fg=_LABEL_FG,
                 font=_MONO_SM).grid(row=row, column=2, sticky="w")
        row += 1

        tk.Label(outer, text="Y offset:", bg=_DARK_BG, fg=_LABEL_FG,
                 font=_MONO_SM).grid(row=row, column=0, sticky="w")
        self._origin_y_var = tk.StringVar(value="0")
        tk.Entry(outer, textvariable=self._origin_y_var, width=8,
                 **_ENTRY).grid(row=row, column=1, sticky="w", padx=(4, 2))
        tk.Label(outer, text="mm", bg=_DARK_BG, fg=_LABEL_FG,
                 font=_MONO_SM).grid(row=row, column=2, sticky="w")
        row += 1

        # Separator
        tk.Frame(outer, bg="#1a3a1a", height=1).grid(
            row=row, column=0, columnspan=3, sticky="ew", pady=6)
        row += 1

        # --- Toolpath type ---
        tk.Label(outer, text="Toolpath Type", bg=_DARK_BG, fg=_TITLE_FG,
                 font=_MONO_SM).grid(row=row, column=0, columnspan=3,
                                     sticky="w", pady=(0, 2))
        row += 1

        toolpath_opts = (
            IMAGE_TOOLPATH_TYPES if self._import_type == "image"
            else VECTOR_TOOLPATH_TYPES
        )
        self._toolpath_var = tk.StringVar(value=toolpath_opts[0])
        cb = ttk.Combobox(
            outer, textvariable=self._toolpath_var,
            values=toolpath_opts, state="readonly", width=30,
        )
        cb.grid(row=row, column=0, columnspan=3, sticky="w", pady=(0, 4))
        cb.bind("<<ComboboxSelected>>", self._on_type_change)
        row += 1

        # --- Type-specific options (dynamic) ---
        self._options_frame = tk.Frame(outer, bg=_DARK_BG)
        self._options_frame.grid(row=row, column=0, columnspan=3,
                                  sticky="ew", pady=(0, 4))
        row += 1

        # Build all option sub-frames and show the first matching one
        self._option_frames: Dict[str, tk.Frame] = {}
        self._build_option_frames()
        self._show_option_frame(toolpath_opts[0])

        # Separator
        tk.Frame(outer, bg="#1a3a1a", height=1).grid(
            row=row, column=0, columnspan=3, sticky="ew", pady=6)
        row += 1

        # --- Power / Speed ---
        ps_frame = tk.Frame(outer, bg=_DARK_BG)
        ps_frame.grid(row=row, column=0, columnspan=3, sticky="ew", pady=(0, 4))
        tk.Label(ps_frame, text="Power (S):", bg=_DARK_BG, fg=_LABEL_FG,
                 font=_MONO_SM).pack(side="left")
        self._power_var = tk.StringVar(value=str(int(default_power)))
        tk.Entry(ps_frame, textvariable=self._power_var, width=6,
                 **_ENTRY).pack(side="left", padx=(4, 12))
        tk.Label(ps_frame, text="Feed (F):", bg=_DARK_BG, fg=_LABEL_FG,
                 font=_MONO_SM).pack(side="left")
        self._speed_var = tk.StringVar(value=str(int(default_speed)))
        tk.Entry(ps_frame, textvariable=self._speed_var, width=7,
                 **_ENTRY).pack(side="left", padx=(4, 4))
        tk.Label(ps_frame, text="mm/min", bg=_DARK_BG, fg=_LABEL_FG,
                 font=_MONO_SM).pack(side="left")
        row += 1

        # --- Buttons ---
        btn_row = tk.Frame(outer, bg=_DARK_BG)
        btn_row.grid(row=row, column=0, columnspan=3, pady=(6, 0))
        tk.Button(btn_row, text="  OK  ", command=self._ok, **_BTN).pack(
            side="left", padx=4)
        tk.Button(btn_row, text="Cancel", command=self._cancel,
                  bg="#4a1a1a", fg="#ffcccc",
                  activebackground="#6a2a2a", activeforeground="#ffffff",
                  relief="flat", padx=8, pady=3,
                  font=_MONO_SM, cursor="hand2").pack(side="left", padx=4)

        self.bind("<Return>", lambda _: self._ok())
        self.bind("<Escape>", lambda _: self._cancel())

        # Draw the preview after the window is ready
        self.after(50, self._draw_preview)

    def _build_option_frames(self) -> None:
        """Pre-build all type-specific option frames inside ``_options_frame``."""

        def _lbl(parent, text):
            tk.Label(parent, text=text, bg=_DARK_BG, fg=_LABEL_FG,
                     font=_MONO_SM).grid(row=0, column=0, sticky="w")

        # ---- Fill / Raster ----
        f = tk.Frame(self._options_frame, bg=_DARK_BG)
        self._line_spacing_var = tk.StringVar(value="0.1")
        self._threshold_var = tk.StringVar(value="0.5")
        row = 0
        tk.Label(f, text="Line spacing:", bg=_DARK_BG, fg=_LABEL_FG,
                 font=_MONO_SM).grid(row=row, column=0, sticky="w")
        tk.Entry(f, textvariable=self._line_spacing_var, width=6,
                 **_ENTRY).grid(row=row, column=1, padx=4)
        tk.Label(f, text="mm", bg=_DARK_BG, fg=_LABEL_FG,
                 font=_MONO_SM).grid(row=row, column=2, sticky="w")
        row += 1
        tk.Label(f, text="Threshold:", bg=_DARK_BG, fg=_LABEL_FG,
                 font=_MONO_SM).grid(row=row, column=0, sticky="w")
        tk.Entry(f, textvariable=self._threshold_var, width=6,
                 **_ENTRY).grid(row=row, column=1, padx=4)
        tk.Label(f, text="(0–1)", bg=_DARK_BG, fg=_LABEL_FG,
                 font=_MONO_SM).grid(row=row, column=2, sticky="w")
        self._option_frames["Fill (Raster Engraving)"] = f

        # ---- Hatch Fill ----
        f = tk.Frame(self._options_frame, bg=_DARK_BG)
        self._hatch_spacing_var = tk.StringVar(value="0.2")
        self._hatch_angle_var = tk.StringVar(value="45")
        self._hatch_cross_var = tk.BooleanVar(value=False)
        row = 0
        tk.Label(f, text="Line spacing:", bg=_DARK_BG, fg=_LABEL_FG,
                 font=_MONO_SM).grid(row=row, column=0, sticky="w")
        tk.Entry(f, textvariable=self._hatch_spacing_var, width=6,
                 **_ENTRY).grid(row=row, column=1, padx=4)
        tk.Label(f, text="mm", bg=_DARK_BG, fg=_LABEL_FG,
                 font=_MONO_SM).grid(row=row, column=2, sticky="w")
        row += 1
        tk.Label(f, text="Angle:", bg=_DARK_BG, fg=_LABEL_FG,
                 font=_MONO_SM).grid(row=row, column=0, sticky="w")
        tk.Entry(f, textvariable=self._hatch_angle_var, width=6,
                 **_ENTRY).grid(row=row, column=1, padx=4)
        tk.Label(f, text="°", bg=_DARK_BG, fg=_LABEL_FG,
                 font=_MONO_SM).grid(row=row, column=2, sticky="w")
        row += 1
        tk.Checkbutton(
            f, text="Crosshatch (add 90° pass)", variable=self._hatch_cross_var,
            bg=_DARK_BG, fg=_LABEL_FG, selectcolor="#0a120a",
            activebackground=_DARK_BG, font=_MONO_SM,
        ).grid(row=row, column=0, columnspan=3, sticky="w")
        self._option_frames["Hatch Fill"] = f

        # ---- Offset Fill ----
        f = tk.Frame(self._options_frame, bg=_DARK_BG)
        self._offset_dist_var = tk.StringVar(value="0.5")
        self._offset_count_var = tk.StringVar(value="5")
        row = 0
        tk.Label(f, text="Offset dist:", bg=_DARK_BG, fg=_LABEL_FG,
                 font=_MONO_SM).grid(row=row, column=0, sticky="w")
        tk.Entry(f, textvariable=self._offset_dist_var, width=6,
                 **_ENTRY).grid(row=row, column=1, padx=4)
        tk.Label(f, text="mm", bg=_DARK_BG, fg=_LABEL_FG,
                 font=_MONO_SM).grid(row=row, column=2, sticky="w")
        row += 1
        tk.Label(f, text="Passes:", bg=_DARK_BG, fg=_LABEL_FG,
                 font=_MONO_SM).grid(row=row, column=0, sticky="w")
        tk.Entry(f, textvariable=self._offset_count_var, width=6,
                 **_ENTRY).grid(row=row, column=1, padx=4)
        self._option_frames["Offset Fill"] = f

        # ---- Image / Dithered (FS) ----
        f = tk.Frame(self._options_frame, bg=_DARK_BG)
        self._fs_threshold_var = tk.StringVar(value="0.5")
        row = 0
        tk.Label(f, text="Threshold:", bg=_DARK_BG, fg=_LABEL_FG,
                 font=_MONO_SM).grid(row=row, column=0, sticky="w")
        tk.Entry(f, textvariable=self._fs_threshold_var, width=6,
                 **_ENTRY).grid(row=row, column=1, padx=4)
        tk.Label(f, text="(0–1)", bg=_DARK_BG, fg=_LABEL_FG,
                 font=_MONO_SM).grid(row=row, column=2, sticky="w")
        self._option_frames["Image (Floyd-Steinberg Dither)"] = f

        # ---- Image / Jarvis ----
        f = tk.Frame(self._options_frame, bg=_DARK_BG)
        self._jarvis_threshold_var = tk.StringVar(value="0.5")
        row = 0
        tk.Label(f, text="Threshold:", bg=_DARK_BG, fg=_LABEL_FG,
                 font=_MONO_SM).grid(row=row, column=0, sticky="w")
        tk.Entry(f, textvariable=self._jarvis_threshold_var, width=6,
                 **_ENTRY).grid(row=row, column=1, padx=4)
        tk.Label(f, text="(0–1)", bg=_DARK_BG, fg=_LABEL_FG,
                 font=_MONO_SM).grid(row=row, column=2, sticky="w")
        self._option_frames["Image (Jarvis Dither)"] = f

        # ---- Greyscale / Variable Power ----
        f = tk.Frame(self._options_frame, bg=_DARK_BG)
        tk.Label(
            f, text="Power varies per pixel based on brightness.",
            bg=_DARK_BG, fg=_LABEL_FG, font=_MONO_SM,
        ).grid(row=0, column=0, sticky="w")
        tk.Label(
            f, text="Dark → full power, Light → low power.",
            bg=_DARK_BG, fg=_LABEL_FG, font=_MONO_SM,
        ).grid(row=1, column=0, sticky="w")
        self._option_frames["Greyscale (Variable Power)"] = f

        # ---- Perforation ----
        f = tk.Frame(self._options_frame, bg=_DARK_BG)
        self._dash_mm_var = tk.StringVar(value="2.0")
        self._gap_mm_var = tk.StringVar(value="1.0")
        row = 0
        tk.Label(f, text="Dash length:", bg=_DARK_BG, fg=_LABEL_FG,
                 font=_MONO_SM).grid(row=row, column=0, sticky="w")
        tk.Entry(f, textvariable=self._dash_mm_var, width=6,
                 **_ENTRY).grid(row=row, column=1, padx=4)
        tk.Label(f, text="mm", bg=_DARK_BG, fg=_LABEL_FG,
                 font=_MONO_SM).grid(row=row, column=2, sticky="w")
        row += 1
        tk.Label(f, text="Gap length:", bg=_DARK_BG, fg=_LABEL_FG,
                 font=_MONO_SM).grid(row=row, column=0, sticky="w")
        tk.Entry(f, textvariable=self._gap_mm_var, width=6,
                 **_ENTRY).grid(row=row, column=1, padx=4)
        tk.Label(f, text="mm", bg=_DARK_BG, fg=_LABEL_FG,
                 font=_MONO_SM).grid(row=row, column=2, sticky="w")
        self._option_frames["Perforation (Dash/Score)"] = f

        # ---- Knife / Drag ----
        f = tk.Frame(self._options_frame, bg=_DARK_BG)
        self._blade_offset_var = tk.StringVar(value="0.5")
        row = 0
        tk.Label(f, text="Blade offset:", bg=_DARK_BG, fg=_LABEL_FG,
                 font=_MONO_SM).grid(row=row, column=0, sticky="w")
        tk.Entry(f, textvariable=self._blade_offset_var, width=6,
                 **_ENTRY).grid(row=row, column=1, padx=4)
        tk.Label(f, text="mm", bg=_DARK_BG, fg=_LABEL_FG,
                 font=_MONO_SM).grid(row=row, column=2, sticky="w")
        self._option_frames["Knife/Drag"] = f

        # ---- Spiral ----
        f = tk.Frame(self._options_frame, bg=_DARK_BG)
        self._spiral_r_start_var = tk.StringVar(value="0.0")
        self._spiral_r_end_var = tk.StringVar(value="20.0")
        self._spiral_spacing_var = tk.StringVar(value="0.5")
        row = 0
        for lbl, var in [
            ("Inner radius:", self._spiral_r_start_var),
            ("Outer radius:", self._spiral_r_end_var),
            ("Spacing:",      self._spiral_spacing_var),
        ]:
            tk.Label(f, text=lbl, bg=_DARK_BG, fg=_LABEL_FG,
                     font=_MONO_SM).grid(row=row, column=0, sticky="w")
            tk.Entry(f, textvariable=var, width=6,
                     **_ENTRY).grid(row=row, column=1, padx=4)
            tk.Label(f, text="mm", bg=_DARK_BG, fg=_LABEL_FG,
                     font=_MONO_SM).grid(row=row, column=2, sticky="w")
            row += 1
        self._option_frames["Spiral Toolpath"] = f

        # ---- Line (Cut) and Optimization have no extra options ----
        for key in ("Line (Cut)", "Optimization"):
            f = tk.Frame(self._options_frame, bg=_DARK_BG)
            tk.Label(
                f,
                text="No additional options." if key == "Line (Cut)"
                else "Reorders cuts to minimise travel distance.",
                bg=_DARK_BG, fg=_LABEL_FG, font=_MONO_SM,
            ).grid(row=0, column=0, sticky="w")
            self._option_frames[key] = f

    def _show_option_frame(self, toolpath_type: str) -> None:
        """Hide all option frames and show the one matching *toolpath_type*."""
        for f in self._option_frames.values():
            f.grid_forget()
        frame = self._option_frames.get(toolpath_type)
        if frame:
            frame.grid(row=0, column=0, sticky="ew")

    # ------------------------------------------------------------------
    # Preview rendering
    # ------------------------------------------------------------------

    def _draw_preview(self) -> None:
        """Render a preview of the imported design in ``_prev_canvas``."""
        c = self._prev_canvas
        c.delete("all")
        w = c.winfo_width() or _PREV_W
        h = c.winfo_height() or _PREV_H
        margin = 8

        if self._preview_grid is not None:
            self._draw_preview_image(c, w, h, margin)
        elif self._preview_paths:
            self._draw_preview_paths(c, w, h, margin)
        else:
            c.create_text(
                w // 2, h // 2,
                text="No preview available",
                fill=_LABEL_FG, font=_MONO_SM,
            )

    def _draw_preview_paths(
        self,
        c: tk.Canvas,
        w: int,
        h: int,
        margin: int,
    ) -> None:
        """Render vector path preview."""
        paths = self._preview_paths
        if not paths:
            return

        # Compute bounding box of all points
        all_pts = [pt for path in paths for pt in path]
        if not all_pts:
            return
        xs = [p[0] for p in all_pts]
        ys = [p[1] for p in all_pts]
        min_x, max_x = min(xs), max(xs)
        min_y, max_y = min(ys), max(ys)

        span_x = max(max_x - min_x, 1e-6)
        span_y = max(max_y - min_y, 1e-6)
        avail_w = w - 2 * margin
        avail_h = h - 2 * margin
        scale = min(avail_w / span_x, avail_h / span_y)

        cx_off = margin + (avail_w - span_x * scale) / 2
        cy_off = margin + (avail_h - span_y * scale) / 2

        def _tx(px: float) -> float:
            return cx_off + (px - min_x) * scale

        def _ty(py: float) -> float:
            return cy_off + (max_y - py) * scale  # flip Y

        for path in paths:
            if len(path) < 2:
                continue
            pts_flat: List[float] = []
            for px, py in path:
                pts_flat += [_tx(px), _ty(py)]
            if len(pts_flat) >= 4:
                c.create_line(*pts_flat, fill=_PREV_LINE, width=1)

    def _draw_preview_image(
        self,
        c: tk.Canvas,
        w: int,
        h: int,
        margin: int,
    ) -> None:
        """Render a downsampled grayscale image preview."""
        grid = self._preview_grid
        if not grid:
            return
        gh = len(grid)
        gw = len(grid[0]) if gh > 0 else 0
        if gw == 0 or gh == 0:
            return

        avail_w = w - 2 * margin
        avail_h = h - 2 * margin

        # Target display dimensions (preserve aspect ratio, max avail)
        aspect = gw / gh
        if aspect > avail_w / max(avail_h, 1):
            disp_w = avail_w
            disp_h = max(1, int(avail_w / aspect))
        else:
            disp_h = avail_h
            disp_w = max(1, int(avail_h * aspect))

        x0 = margin + (avail_w - disp_w) // 2
        y0 = margin + (avail_h - disp_h) // 2

        # Build PhotoImage via put() rows
        img = tk.PhotoImage(width=disp_w, height=disp_h)
        for row_idx in range(disp_h):
            src_row = int(row_idx * gh / disp_h)
            src_row = min(src_row, gh - 1)
            row_data = []
            for col_idx in range(disp_w):
                src_col = int(col_idx * gw / disp_w)
                src_col = min(src_col, gw - 1)
                v = int(max(0.0, min(1.0, grid[src_row][src_col])) * 255)
                row_data.append(f"#{v:02x}{v:02x}{v:02x}")
            img.put("{" + " ".join(row_data) + "}", to=(0, row_idx))

        # Keep a reference so it's not garbage-collected, then render
        c._preview_img = img  # type: ignore[attr-defined]
        c.create_image(x0, y0, image=img, anchor="nw")

    # ------------------------------------------------------------------
    # Event handlers
    # ------------------------------------------------------------------

    def _on_type_change(self, _event=None) -> None:
        self._show_option_frame(self._toolpath_var.get())

    def _on_width_change(self, *_) -> None:
        if not self._lock_ratio_var.get():
            return
        if self._aspect <= 0:
            return
        try:
            w = float(self._width_var.get())
            if w > 0:
                h = w / self._aspect
                self._height_var.set(f"{h:.2f}")
        except ValueError:
            pass

    # ------------------------------------------------------------------
    # OK / Cancel
    # ------------------------------------------------------------------

    def _ok(self) -> None:
        try:
            width_mm = float(self._width_var.get())
        except ValueError:
            width_mm = 0.0
        try:
            height_mm = float(self._height_var.get())
        except ValueError:
            height_mm = 0.0
        try:
            origin_x = float(self._origin_x_var.get())
        except ValueError:
            origin_x = 0.0
        try:
            origin_y = float(self._origin_y_var.get())
        except ValueError:
            origin_y = 0.0
        try:
            power = float(self._power_var.get())
        except ValueError:
            power = 500.0
        try:
            speed = float(self._speed_var.get())
        except ValueError:
            speed = 3000.0

        def _f(var: tk.StringVar, default: float) -> float:
            try:
                return float(var.get())
            except ValueError:
                return default

        def _i(var: tk.StringVar, default: int) -> int:
            try:
                return int(var.get())
            except ValueError:
                return default

        self.result = {
            "toolpath_type": self._toolpath_var.get(),
            "width_mm": width_mm,
            "height_mm": height_mm,
            "lock_ratio": self._lock_ratio_var.get(),
            "origin_x": origin_x,
            "origin_y": origin_y,
            "power": power,
            "speed": speed,
            # Fill / Raster
            "line_spacing": _f(self._line_spacing_var, 0.1),
            "threshold": _f(self._threshold_var, 0.5),
            # Hatch
            "angle": _f(self._hatch_angle_var, 45.0),
            "hatch_spacing": _f(self._hatch_spacing_var, 0.2),
            "crosshatch": self._hatch_cross_var.get(),
            # Offset Fill
            "offset_dist": _f(self._offset_dist_var, 0.5),
            "offset_count": _i(self._offset_count_var, 5),
            # Dithered
            "fs_threshold": _f(self._fs_threshold_var, 0.5),
            "jarvis_threshold": _f(self._jarvis_threshold_var, 0.5),
            # Perforation
            "dash_mm": _f(self._dash_mm_var, 2.0),
            "gap_mm": _f(self._gap_mm_var, 1.0),
            # Knife/Drag
            "blade_offset": _f(self._blade_offset_var, 0.5),
            # Spiral
            "spiral_r_start": _f(self._spiral_r_start_var, 0.0),
            "spiral_r_end": _f(self._spiral_r_end_var, 20.0),
            "spiral_spacing": _f(self._spiral_spacing_var, 0.5),
        }
        self.destroy()

    def _cancel(self) -> None:
        self.result = None
        self.destroy()
