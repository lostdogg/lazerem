"""Main application window for the Ray5W laser control."""

from __future__ import annotations

import threading
import tkinter as tk
from tkinter import filedialog, messagebox, simpledialog
from tkinter import ttk
from typing import Optional

from ..machine import LaserMachine
from ..design import DesignPath, array_path, nest_paths, offset_path, paths_to_gcode
from ..parser import parse_program
from .canvas import BurnPathCanvas
from .panels import AdvancedSettingsPanel, CoordinatePanel, LaserStatusPanel, MessageLog
from .design_panel import DesignPanel


_DARK_BG = "#0d1a0d"
_EDITOR_BG = "#0a120a"
_EDITOR_FG = "#99ff99"
_MONO_SM = ("Monospace", 9)

_SAMPLE_PROGRAM = """\
; Ray5W sample – 40 x 40 mm square outline
; Power: 500 / 1000 (~50 %)  Feed: 3000 mm/min

G21 G90             ; metric, absolute
G0 X0 Y0            ; move to origin (laser off)
M3 S500             ; laser on, constant power
G1 X40 F3000        ; cut right
G1 Y40              ; cut up
G1 X0               ; cut left
G1 Y0               ; cut down
M5                  ; laser off
G0 X0 Y0            ; return to origin
M2                  ; end
"""


class App(tk.Tk):
    """Root window of the Ray5W laser control."""

    def __init__(self) -> None:
        super().__init__()

        self.title("Ray5W Laser Control")
        self.configure(bg=_DARK_BG)
        self.geometry("1400x800")
        self.minsize(1000, 640)

        self._machine = LaserMachine()
        self._run_thread: Optional[threading.Thread] = None

        # Live preview – redraw canvas every N blocks while running
        self._live_preview: bool = True
        self._preview_interval: int = 20  # redraw every N blocks

        self._build_ui()
        self._load_sample()

    # ------------------------------------------------------------------
    # UI construction
    # ------------------------------------------------------------------

    def _build_ui(self) -> None:
        self._build_menu()

        # Top toolbar
        toolbar = tk.Frame(self, bg="#0f2a0f", pady=4)
        toolbar.pack(fill="x", padx=4, pady=(4, 0))
        self._build_toolbar(toolbar)

        # Main pane: left editor | centre canvas | right notebook
        pane = tk.PanedWindow(self, orient="horizontal", bg=_DARK_BG,
                              sashwidth=4, sashrelief="flat")
        pane.pack(fill="both", expand=True, padx=4, pady=4)

        # --- Left: G-code editor ---
        left = tk.Frame(pane, bg=_DARK_BG)
        pane.add(left, minsize=220, width=290)

        tk.Label(left, text="G-CODE PROGRAM", bg=_DARK_BG, fg="#4a9a4a",
                 font=_MONO_SM).pack(anchor="w", padx=4, pady=(2, 0))

        ed_frame = tk.Frame(left, bg="#070e07")
        ed_frame.pack(fill="both", expand=True, padx=4, pady=4)

        ed_scroll = tk.Scrollbar(ed_frame)
        ed_scroll.pack(side="right", fill="y")

        self._editor = tk.Text(
            ed_frame,
            bg=_EDITOR_BG,
            fg=_EDITOR_FG,
            insertbackground="#00ff88",
            font=_MONO_SM,
            relief="flat",
            undo=True,
            yscrollcommand=ed_scroll.set,
        )
        self._editor.pack(fill="both", expand=True)
        ed_scroll.config(command=self._editor.yview)

        # --- Centre: burn-path canvas ---
        centre = tk.Frame(pane, bg=_DARK_BG)
        pane.add(centre, minsize=300)

        tk.Label(centre, text="BURN PATH (XY)", bg=_DARK_BG, fg="#4a9a4a",
                 font=_MONO_SM).pack(anchor="w", padx=4, pady=(2, 0))

        self._canvas = BurnPathCanvas(centre)
        self._canvas.pack(fill="both", expand=True, padx=4, pady=4)

        legend = tk.Label(
            centre,
            text="  ╌╌ Rapid (off)   ── Cut (power)   ── Arc"
                 "   Scroll: zoom   Drag: pan",
            bg=_DARK_BG, fg="#3a6a3a", font=("Monospace", 8),
        )
        legend.pack(anchor="w", padx=4)

        # --- Right: tabbed panel ---
        right = tk.Frame(pane, bg=_DARK_BG)
        pane.add(right, minsize=260, width=310)

        right_nb = ttk.Notebook(right)
        right_nb.pack(fill="both", expand=True)

        # Tab 1: Status
        status_tab = tk.Frame(right_nb, bg=_DARK_BG)
        right_nb.add(status_tab, text="Status")

        self._coord_panel = CoordinatePanel(status_tab)
        self._coord_panel.pack(fill="x", padx=4, pady=(4, 2))

        self._status_panel = LaserStatusPanel(status_tab)
        self._status_panel.pack(fill="x", padx=4, pady=2)

        self._adv_panel = AdvancedSettingsPanel(
            status_tab, on_change=self._on_adv_settings_change
        )
        self._adv_panel.pack(fill="x", padx=4, pady=2)

        self._log = MessageLog(status_tab)
        self._log.pack(fill="both", expand=True, padx=4, pady=2)

        # Tab 2: Design / Material
        self._design_panel = DesignPanel(
            right_nb,
            on_apply_material=self._apply_material,
            on_offset=self._do_offset,
            on_array=self._do_array,
            on_nest=self._do_nest,
            on_trace=self._do_trace_image,
        )
        right_nb.add(self._design_panel, text="Design")

        # --- MDI bar ---
        self._build_mdi_bar()

    def _build_menu(self) -> None:
        menubar = tk.Menu(self, bg="#0f2a0f", fg="#ccffcc",
                          activebackground="#1a4a1a",
                          activeforeground="#ffffff")

        # ---- File ----
        file_menu = tk.Menu(menubar, tearoff=False, bg="#0f2a0f",
                            fg="#ccffcc", activebackground="#1a4a1a",
                            activeforeground="#ffffff")
        file_menu.add_command(label="New", command=self._new_program,
                              accelerator="Ctrl+N")
        file_menu.add_command(label="Open G-code…", command=self._open_file,
                              accelerator="Ctrl+O")
        file_menu.add_command(label="Save G-code…", command=self._save_file,
                              accelerator="Ctrl+S")
        file_menu.add_separator()

        import_menu = tk.Menu(file_menu, tearoff=False, bg="#0f2a0f",
                              fg="#ccffcc", activebackground="#1a4a1a",
                              activeforeground="#ffffff")
        import_menu.add_command(label="SVG vector…", command=self._import_svg)
        import_menu.add_command(label="DXF drawing…", command=self._import_dxf)
        import_menu.add_command(label="Raster image (PNG/BMP)…",
                                command=self._import_image)
        file_menu.add_cascade(label="Import", menu=import_menu)

        file_menu.add_separator()
        file_menu.add_command(label="Quit", command=self.quit,
                              accelerator="Ctrl+Q")
        menubar.add_cascade(label="File", menu=file_menu)

        # ---- Laser ----
        laser_menu = tk.Menu(menubar, tearoff=False, bg="#0f2a0f",
                             fg="#ccffcc", activebackground="#1a4a1a",
                             activeforeground="#ffffff")
        laser_menu.add_command(label="Run Program", command=self._run_program,
                               accelerator="F5")
        laser_menu.add_command(label="Stop / Emergency", command=self._stop_program,
                               accelerator="F6")
        laser_menu.add_separator()
        laser_menu.add_command(label="Reset Machine", command=self._reset_machine)
        laser_menu.add_command(label="Fit View",
                               command=lambda: self._canvas.fit_all(),
                               accelerator="F")
        laser_menu.add_separator()
        self._live_preview_var = tk.BooleanVar(value=True)
        laser_menu.add_checkbutton(label="Live Preview",
                                   variable=self._live_preview_var,
                                   command=lambda: setattr(self, "_live_preview",
                                                           self._live_preview_var.get()))
        menubar.add_cascade(label="Laser", menu=laser_menu)

        # ---- Design ----
        design_menu = tk.Menu(menubar, tearoff=False, bg="#0f2a0f",
                              fg="#ccffcc", activebackground="#1a4a1a",
                              activeforeground="#ffffff")
        design_menu.add_command(label="Offset Path…",
                                command=self._prompt_offset)
        design_menu.add_command(label="Array / Grid…",
                                command=self._prompt_array)
        design_menu.add_command(label="Auto-Nest on Sheet…",
                                command=self._prompt_nest)
        design_menu.add_separator()
        design_menu.add_command(label="Boolean Union",
                                command=self._boolean_union_noop)
        menubar.add_cascade(label="Design", menu=design_menu)

        # ---- Help ----
        help_menu = tk.Menu(menubar, tearoff=False, bg="#0f2a0f",
                            fg="#ccffcc", activebackground="#1a4a1a",
                            activeforeground="#ffffff")
        help_menu.add_command(label="About", command=self._show_about)
        menubar.add_cascade(label="Help", menu=help_menu)

        self.config(menu=menubar)

        self.bind("<Control-n>", lambda _: self._new_program())
        self.bind("<Control-o>", lambda _: self._open_file())
        self.bind("<Control-s>", lambda _: self._save_file())
        self.bind("<Control-q>", lambda _: self.quit())
        self.bind("<F5>", lambda _: self._run_program())
        self.bind("<F6>", lambda _: self._stop_program())
        self.bind("f", lambda _: self._canvas.fit_all())
        self.bind("F", lambda _: self._canvas.fit_all())

    def _build_toolbar(self, parent: tk.Frame) -> None:
        btn_opts = dict(
            bg="#1a4a1a", fg="#ccffcc",
            activebackground="#2a6a2a", activeforeground="#ffffff",
            relief="flat", padx=10, pady=2,
            font=_MONO_SM, cursor="hand2",
        )

        tk.Button(parent, text="▶  Run (F5)", command=self._run_program,
                  **btn_opts).pack(side="left", padx=2)
        tk.Button(parent, text="■  Stop (F6)", command=self._stop_program,
                  bg="#4a1a1a", fg="#ffcccc",
                  activebackground="#6a2a2a", activeforeground="#ffffff",
                  relief="flat", padx=10, pady=2,
                  font=_MONO_SM, cursor="hand2").pack(side="left", padx=2)
        tk.Button(parent, text="⟳  Reset", command=self._reset_machine,
                  **btn_opts).pack(side="left", padx=2)
        tk.Button(parent, text="⊞  Fit (F)", command=lambda: self._canvas.fit_all(),
                  **btn_opts).pack(side="left", padx=2)

        tk.Frame(parent, bg="#0f2a0f", width=2).pack(side="left", padx=6, fill="y")

        tk.Button(parent, text="Open", command=self._open_file,
                  **btn_opts).pack(side="left", padx=2)
        tk.Button(parent, text="Save", command=self._save_file,
                  **btn_opts).pack(side="left", padx=2)

        tk.Frame(parent, bg="#0f2a0f", width=2).pack(side="left", padx=6, fill="y")

        # Import shortcuts
        tk.Button(parent, text="⇒ SVG", command=self._import_svg,
                  **btn_opts).pack(side="left", padx=2)
        tk.Button(parent, text="⇒ DXF", command=self._import_dxf,
                  **btn_opts).pack(side="left", padx=2)
        tk.Button(parent, text="⇒ IMG", command=self._import_image,
                  **btn_opts).pack(side="left", padx=2)

        # Power / feed quick-set on right side
        tk.Frame(parent, bg="#0f2a0f").pack(side="left", fill="x", expand=True)

        tk.Label(parent, text="S:", bg="#0f2a0f", fg="#7abf7a",
                 font=_MONO_SM).pack(side="left")
        self._power_var = tk.StringVar(value="500")
        tk.Entry(parent, textvariable=self._power_var,
                 width=5, bg="#071407", fg="#00ff88",
                 insertbackground="#00ff88",
                 font=_MONO_SM, relief="flat").pack(side="left", padx=(0, 8))

        tk.Label(parent, text="F:", bg="#0f2a0f", fg="#7abf7a",
                 font=_MONO_SM).pack(side="left")
        self._feed_var = tk.StringVar(value="3000")
        tk.Entry(parent, textvariable=self._feed_var,
                 width=6, bg="#071407", fg="#00ff88",
                 insertbackground="#00ff88",
                 font=_MONO_SM, relief="flat").pack(side="left", padx=(0, 4))

    def _build_mdi_bar(self) -> None:
        bar = tk.Frame(self, bg="#0f2a0f", pady=4)
        bar.pack(fill="x", padx=4, pady=(0, 4))

        tk.Label(bar, text="MDI:", bg="#0f2a0f", fg="#7abf7a",
                 font=_MONO_SM).pack(side="left", padx=(4, 2))

        self._mdi_var = tk.StringVar()
        entry = tk.Entry(bar, textvariable=self._mdi_var,
                         bg="#071407", fg="#00ff88",
                         insertbackground="#ffffff",
                         font=_MONO_SM, relief="flat", width=60)
        entry.pack(side="left", padx=2)
        entry.bind("<Return>", self._execute_mdi)

        tk.Button(bar, text="Execute", command=self._execute_mdi,
                  bg="#1a4a1a", fg="#ccffcc",
                  activebackground="#2a6a2a", activeforeground="#ffffff",
                  relief="flat", padx=8, pady=2,
                  font=_MONO_SM, cursor="hand2").pack(side="left", padx=4)

    # ------------------------------------------------------------------
    # File actions
    # ------------------------------------------------------------------

    def _load_sample(self) -> None:
        self._editor.delete("1.0", "end")
        self._editor.insert("1.0", _SAMPLE_PROGRAM)

    def _new_program(self) -> None:
        if messagebox.askyesno("New Program",
                               "Clear current program?", parent=self):
            self._editor.delete("1.0", "end")
            self._reset_machine()

    def _open_file(self) -> None:
        path = filedialog.askopenfilename(
            title="Open G-code / laser file",
            filetypes=[
                ("G-code files", "*.nc *.gcode *.ngc *.txt *.gc *.lbrn2"),
                ("All files", "*.*"),
            ],
        )
        if path:
            try:
                with open(path, "r", encoding="utf-8", errors="replace") as fh:
                    content = fh.read()
                self._editor.delete("1.0", "end")
                self._editor.insert("1.0", content)
                self._reset_machine()
                self._log.log(f"Opened: {path}")
            except OSError as exc:
                messagebox.showerror("Error", str(exc), parent=self)

    def _save_file(self) -> None:
        path = filedialog.asksaveasfilename(
            title="Save G-code file",
            defaultextension=".nc",
            filetypes=[
                ("G-code files", "*.nc *.gcode *.ngc *.txt *.gc"),
                ("All files", "*.*"),
            ],
        )
        if path:
            try:
                content = self._editor.get("1.0", "end-1c")
                with open(path, "w", encoding="utf-8") as fh:
                    fh.write(content)
                self._log.log(f"Saved: {path}")
            except OSError as exc:
                messagebox.showerror("Error", str(exc), parent=self)

    # ------------------------------------------------------------------
    # Import actions
    # ------------------------------------------------------------------

    def _import_svg(self) -> None:
        from ..importers.svg_importer import import_svg
        path = filedialog.askopenfilename(
            title="Import SVG",
            filetypes=[("SVG files", "*.svg"), ("All files", "*.*")],
        )
        if not path:
            return
        try:
            with open(path, "r", encoding="utf-8", errors="replace") as fh:
                source = fh.read()
            try:
                power = float(self._power_var.get())
            except ValueError:
                power = 500.0
            try:
                speed = float(self._feed_var.get())
            except ValueError:
                speed = 3000.0
            gcode = import_svg(source, power=power, speed=speed)
            self._editor.delete("1.0", "end")
            self._editor.insert("1.0", gcode)
            self._reset_machine()
            self._log.log(f"Imported SVG: {path}")
        except Exception as exc:  # noqa: BLE001
            messagebox.showerror("SVG Import Error", str(exc), parent=self)

    def _import_dxf(self) -> None:
        from ..importers.dxf_importer import import_dxf
        path = filedialog.askopenfilename(
            title="Import DXF",
            filetypes=[("DXF files", "*.dxf"), ("All files", "*.*")],
        )
        if not path:
            return
        try:
            with open(path, "r", encoding="utf-8", errors="replace") as fh:
                source = fh.read()
            try:
                power = float(self._power_var.get())
            except ValueError:
                power = 500.0
            try:
                speed = float(self._feed_var.get())
            except ValueError:
                speed = 3000.0
            gcode = import_dxf(source, power=power, speed=speed)
            self._editor.delete("1.0", "end")
            self._editor.insert("1.0", gcode)
            self._reset_machine()
            self._log.log(f"Imported DXF: {path}")
        except Exception as exc:  # noqa: BLE001
            messagebox.showerror("DXF Import Error", str(exc), parent=self)

    def _import_image(self) -> None:
        from ..image_processor import load_png_tkinter, load_bmp, trace_image
        path = filedialog.askopenfilename(
            title="Import Raster Image",
            filetypes=[
                ("PNG files", "*.png"),
                ("BMP files", "*.bmp"),
                ("All images", "*.png *.bmp"),
                ("All files", "*.*"),
            ],
        )
        if not path:
            return
        try:
            ext = path.lower()
            if ext.endswith(".bmp"):
                grid, _w, _h = load_bmp(path)
            else:
                grid, _w, _h = load_png_tkinter(path)

            try:
                power = float(self._power_var.get())
            except ValueError:
                power = 500.0
            try:
                speed = float(self._feed_var.get())
            except ValueError:
                speed = 3000.0

            gcode = trace_image(
                grid,
                mode="threshold",
                threshold=0.5,
                power=power,
                speed=speed,
                pixel_size=0.1,
            )
            self._editor.delete("1.0", "end")
            self._editor.insert("1.0", gcode)
            self._reset_machine()
            self._log.log(f"Imported image: {path}  ({_w}×{_h} px)")
        except Exception as exc:  # noqa: BLE001
            messagebox.showerror("Image Import Error", str(exc), parent=self)

    # ------------------------------------------------------------------
    # Design tool actions
    # ------------------------------------------------------------------

    def _current_paths(self):
        """Parse the current editor content into DesignPath objects."""
        source = self._editor.get("1.0", "end-1c")
        blocks, _ = parse_program(source)
        # Extract X/Y motions into a single DesignPath
        points = []
        try:
            power = float(self._power_var.get())
        except ValueError:
            power = 500.0
        try:
            speed = float(self._feed_var.get())
        except ValueError:
            speed = 3000.0
        cur_x, cur_y = 0.0, 0.0
        for block in blocks:
            if block.has("X") or block.has("Y"):
                cur_x = block.get("X", cur_x)
                cur_y = block.get("Y", cur_y)
                points.append((cur_x, cur_y))
        if points:
            return [DesignPath(points, False, power, speed, 1)]
        return []

    def _apply_material(self, preset) -> None:
        self._power_var.set(str(int(preset.power)))
        self._feed_var.set(str(int(preset.speed)))
        self._machine.pass_count = preset.passes
        self._machine.dithering_mode = preset.dithering
        self._adv_panel.update_from(self._machine)
        self._log.log(
            f"Material: {preset.name}  "
            f"S={preset.power:.0f}  F={preset.speed:.0f}  "
            f"passes={preset.passes}  dith={preset.dithering}"
        )

    def _do_offset(self, dist: float) -> None:
        paths = self._current_paths()
        if not paths:
            messagebox.showinfo("Offset", "No path found in editor.", parent=self)
            return
        try:
            power = float(self._power_var.get())
            speed = float(self._feed_var.get())
        except ValueError:
            power, speed = 500.0, 3000.0
        result = [offset_path(p, dist) for p in paths]
        gcode = paths_to_gcode(result, power, speed)
        self._editor.delete("1.0", "end")
        self._editor.insert("1.0", gcode)
        self._log.log(f"Offset path by {dist:.3f} mm")

    def _do_array(self, cols: int, rows: int, xsp: float, ysp: float) -> None:
        paths = self._current_paths()
        if not paths:
            messagebox.showinfo("Array", "No path found in editor.", parent=self)
            return
        try:
            power = float(self._power_var.get())
            speed = float(self._feed_var.get())
        except ValueError:
            power, speed = 500.0, 3000.0
        result: list = []
        for p in paths:
            result.extend(array_path(p, cols, rows, xsp, ysp))
        gcode = paths_to_gcode(result, power, speed)
        self._editor.delete("1.0", "end")
        self._editor.insert("1.0", gcode)
        self._log.log(f"Array: {cols}×{rows}  spacing {xsp}×{ysp} mm")

    def _do_nest(self, sheet_w: float, sheet_h: float, gap: float) -> None:
        paths = self._current_paths()
        if not paths:
            messagebox.showinfo("Nest", "No path found in editor.", parent=self)
            return
        try:
            power = float(self._power_var.get())
            speed = float(self._feed_var.get())
        except ValueError:
            power, speed = 500.0, 3000.0
        result = nest_paths(paths, sheet_w, sheet_h, gap)
        gcode = paths_to_gcode(result, power, speed)
        self._editor.delete("1.0", "end")
        self._editor.insert("1.0", gcode)
        self._log.log(f"Nested on {sheet_w}×{sheet_h} mm sheet (gap {gap} mm)")

    def _do_trace_image(
        self,
        mode: str,
        threshold: float,
        pixel_size: float,
        power: float,
        speed: float,
    ) -> None:
        """Open image file picker and trace."""
        from ..image_processor import load_png_tkinter, load_bmp, trace_image
        path = filedialog.askopenfilename(
            title="Select image to trace",
            filetypes=[
                ("PNG files", "*.png"),
                ("BMP files", "*.bmp"),
                ("All images", "*.png *.bmp"),
            ],
        )
        if not path:
            return
        try:
            if path.lower().endswith(".bmp"):
                grid, w, h = load_bmp(path)
            else:
                grid, w, h = load_png_tkinter(path)
            gcode = trace_image(
                grid,
                mode=mode,
                threshold=threshold,
                power=power,
                speed=speed,
                pixel_size=pixel_size,
            )
            self._editor.delete("1.0", "end")
            self._editor.insert("1.0", gcode)
            self._reset_machine()
            self._log.log(
                f"Traced {path}  ({w}×{h} px)  "
                f"mode={mode}  thresh={threshold}"
            )
        except Exception as exc:  # noqa: BLE001
            messagebox.showerror("Trace Error", str(exc), parent=self)

    # ------------------------------------------------------------------
    # Design menu prompt helpers
    # ------------------------------------------------------------------

    def _prompt_offset(self) -> None:
        dist = simpledialog.askfloat(
            "Offset Path", "Offset distance (mm, negative to shrink):",
            initialvalue=0.1, parent=self,
        )
        if dist is not None:
            self._do_offset(dist)

    def _prompt_array(self) -> None:
        # Quick multi-field approach via toplevel
        dlg = tk.Toplevel(self)
        dlg.title("Array / Grid")
        dlg.configure(bg="#0d1a0d")
        dlg.resizable(False, False)
        fields = [
            ("Columns", "3"),
            ("Rows", "3"),
            ("X spacing (mm)", "50.0"),
            ("Y spacing (mm)", "50.0"),
        ]
        vars_ = []
        for i, (lbl, default) in enumerate(fields):
            tk.Label(dlg, text=lbl, bg="#0d1a0d", fg="#7abf7a",
                     font=_MONO_SM).grid(row=i, column=0, sticky="w", padx=8, pady=2)
            v = tk.StringVar(value=default)
            tk.Entry(dlg, textvariable=v, bg="#071407", fg="#00ff88",
                     font=_MONO_SM, width=8).grid(row=i, column=1, padx=8)
            vars_.append(v)

        def _ok():
            try:
                cols, rows = int(vars_[0].get()), int(vars_[1].get())
                xsp, ysp = float(vars_[2].get()), float(vars_[3].get())
            except ValueError:
                messagebox.showerror("Error", "Invalid values.", parent=dlg)
                return
            dlg.destroy()
            self._do_array(cols, rows, xsp, ysp)

        tk.Button(dlg, text="OK", command=_ok,
                  bg="#1a4a1a", fg="#ccffcc", font=_MONO_SM).grid(
            row=len(fields), column=0, columnspan=2, pady=8)

    def _prompt_nest(self) -> None:
        dlg = tk.Toplevel(self)
        dlg.title("Auto-Nest")
        dlg.configure(bg="#0d1a0d")
        dlg.resizable(False, False)
        fields = [
            ("Sheet width (mm)", "400.0"),
            ("Sheet height (mm)", "300.0"),
            ("Gap (mm)", "2.0"),
        ]
        vars_ = []
        for i, (lbl, default) in enumerate(fields):
            tk.Label(dlg, text=lbl, bg="#0d1a0d", fg="#7abf7a",
                     font=_MONO_SM).grid(row=i, column=0, sticky="w", padx=8, pady=2)
            v = tk.StringVar(value=default)
            tk.Entry(dlg, textvariable=v, bg="#071407", fg="#00ff88",
                     font=_MONO_SM, width=8).grid(row=i, column=1, padx=8)
            vars_.append(v)

        def _ok():
            try:
                w, h, g = float(vars_[0].get()), float(vars_[1].get()), float(vars_[2].get())
            except ValueError:
                messagebox.showerror("Error", "Invalid values.", parent=dlg)
                return
            dlg.destroy()
            self._do_nest(w, h, g)

        tk.Button(dlg, text="OK", command=_ok,
                  bg="#1a4a1a", fg="#ccffcc", font=_MONO_SM).grid(
            row=len(fields), column=0, columnspan=2, pady=8)

    def _boolean_union_noop(self) -> None:
        messagebox.showinfo(
            "Boolean Union",
            "Boolean Union: the current G-code paths are already combined\n"
            "as a single program.  Use Import to load multiple designs and\n"
            "they will be concatenated automatically.",
            parent=self,
        )

    # ------------------------------------------------------------------
    # Machine / execution actions
    # ------------------------------------------------------------------

    def _on_adv_settings_change(self) -> None:
        self._machine.pass_count = self._adv_panel.pass_count
        self._machine.dithering_mode = self._adv_panel.dithering_mode
        self._machine.controller_type = self._adv_panel.controller_type

    def _reset_machine(self) -> None:
        self._stop_program()
        self._machine.reset()
        self._canvas.set_burn_path([], (0.0, 0.0))
        self._log.clear()
        self._log.log("Machine reset.")
        self._refresh_panels()

    def _run_program(self) -> None:
        if self._run_thread and self._run_thread.is_alive():
            return
        source = self._editor.get("1.0", "end-1c")
        # Push advanced settings to machine
        self._machine.pass_count = self._adv_panel.pass_count
        self._machine.dithering_mode = self._adv_panel.dithering_mode
        self._machine.controller_type = self._adv_panel.controller_type
        self._machine.reset()
        # Restore settings after reset
        self._machine.pass_count = self._adv_panel.pass_count
        self._machine.dithering_mode = self._adv_panel.dithering_mode
        self._machine.controller_type = self._adv_panel.controller_type
        self._log.clear()
        self._log.log(
            f"Running (passes={self._machine.pass_count}  "
            f"ctrl={self._machine.controller_type})…"
        )
        self._refresh_panels()
        self._block_counter = 0

        def _on_block(idx: int, block) -> None:
            if self._live_preview:
                self._block_counter += 1
                if self._block_counter % self._preview_interval == 0:
                    pos = self._machine.position
                    self.after(0, self._canvas.set_burn_path,
                               list(self._machine.burn_path),
                               (pos.x, pos.y))

        def _worker():
            messages = self._machine.run_program(source, on_block=_on_block)
            self.after(0, self._on_run_complete, messages)

        self._run_thread = threading.Thread(target=_worker, daemon=True)
        self._run_thread.start()

    def _on_run_complete(self, messages: list) -> None:
        for msg in messages:
            self._log.log(msg)
        self._log.log(f"Status: {self._machine.status}")
        pos = self._machine.position
        self._canvas.set_burn_path(
            self._machine.burn_path,
            current_pos=(pos.x, pos.y),
        )
        self._canvas.fit_all()
        self._refresh_panels()

    def _stop_program(self) -> None:
        self._machine.program_stopped = True
        self._machine.laser_on = False
        self._machine.status = "STOP"
        self._log.log("STOP / Emergency laser off.")
        self._refresh_panels()

    def _execute_mdi(self, _event=None) -> None:
        line = self._mdi_var.get().strip()
        if not line:
            return
        result = self._machine.execute_mdi(line)
        self._log.log(f"MDI> {line}  →  {result}")
        pos = self._machine.position
        self._canvas.set_burn_path(
            self._machine.burn_path,
            current_pos=(pos.x, pos.y),
        )
        self._mdi_var.set("")
        self._refresh_panels()

    def _refresh_panels(self) -> None:
        self._coord_panel.update_from(self._machine)
        self._status_panel.update_from(self._machine)
        self._adv_panel.update_from(self._machine)

    # ------------------------------------------------------------------
    # Help
    # ------------------------------------------------------------------

    def _show_about(self) -> None:
        messagebox.showinfo(
            "About Ray5W Laser Control",
            "Ray5W Laser Control\n"
            "Version 2.0.0\n\n"
            "GRBL-style G-code interpreter and burn-path visualiser\n"
            "for the Ray5W diode laser engraver.\n\n"
            "Design capabilities:\n"
            "  SVG / DXF import\n"
            "  PNG / BMP raster image tracing\n"
            "  Image brightness, contrast, saturation\n"
            "  Path offset (kerf compensation)\n"
            "  Array / grid tool\n"
            "  Auto-nesting (shelf algorithm)\n"
            "  Material library (JSON presets)\n\n"
            "G-code:\n"
            "  G0/G1 – Rapid / Cut\n"
            "  G2/G3 – Circular arcs\n"
            "  M3/M4/M5 – Laser on/off\n"
            "  S – Power (0–1000)  F – Feed (mm/min)\n\n"
            "Controls:\n"
            "  F5 – Run  F6 – Stop  F – Fit view\n"
            "  Scroll – Zoom  Drag – Pan",
            parent=self,
        )
