"""Main application window for the Ray5W laser control."""

from __future__ import annotations

import glob
import os
import sys
import threading
import tkinter as tk
from tkinter import filedialog, messagebox, simpledialog
from tkinter import ttk
from typing import Dict, Optional

from ..machine import LaserMachine
from ..design import DesignPath, array_path, nest_paths, offset_path, paths_to_gcode
from ..drawing import DrawingDocument, drawing_to_gcode
from ..parser import parse_program
from ..job_queue import JobQueue, QueuedJob
from ..cost_estimator import CostEstimator
from ..path_optimizer import PathOptimizer
from ..error_monitor import ErrorMonitor
from ..plugin_manager import PluginManager
from .canvas import BurnPathCanvas
from .panels import AdvancedSettingsPanel, CoordinatePanel, LaserStatusPanel, MessageLog
from .design_panel import DesignPanel
from .simulation_canvas import SimulationCanvas
from .job_queue_panel import JobQueuePanel
from .cost_panel import CostPanel
from .import_dialog import ImportParamsDialog
from .drawing_canvas import DrawingCanvas
from .layers_panel import LayersPanel


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
        self._job_queue = JobQueue()
        self._plugin_manager = PluginManager()
        self._plugin_manager.load_all()
        self._optimizer = PathOptimizer()
        self._error_monitor = ErrorMonitor(
            self._machine,
            on_alert=self._on_monitor_alert,
        )

        # Live preview – redraw canvas every N blocks while running
        self._live_preview: bool = True
        self._preview_interval: int = 20  # redraw every N blocks

        # COM port state (no actual serial in this build – UI only)
        self._com_port: str = ""
        self._com_connected: bool = False

        # Drawing document (persists for the session)
        self._draw_doc = DrawingDocument()
        self._draw_doc.add_layer("Layer 1")      # default cut layer

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

        # --- Centre: tabbed canvas area ---
        centre = tk.Frame(pane, bg=_DARK_BG)
        pane.add(centre, minsize=300)

        centre_nb = ttk.Notebook(centre)
        centre_nb.pack(fill="both", expand=True)

        # Centre tab 1: Burn Path (existing visualisation)
        burn_tab = tk.Frame(centre_nb, bg=_DARK_BG)
        centre_nb.add(burn_tab, text="Burn Path")

        tk.Label(burn_tab, text="BURN PATH (XY)", bg=_DARK_BG, fg="#4a9a4a",
                 font=_MONO_SM).pack(anchor="w", padx=4, pady=(2, 0))

        self._canvas = BurnPathCanvas(burn_tab)
        self._canvas.pack(fill="both", expand=True, padx=4, pady=4)

        tk.Label(
            burn_tab,
            text="  ╌╌ Rapid (off)   ── Cut (power)   ── Arc"
                 "   Scroll: zoom   Drag: pan",
            bg=_DARK_BG, fg="#3a6a3a", font=("Monospace", 8),
        ).pack(anchor="w", padx=4)

        # Centre tab 2: Draw
        draw_tab = tk.Frame(centre_nb, bg=_DARK_BG)
        centre_nb.add(draw_tab, text="Draw")

        # Drawing toolbar (inside Draw tab)
        self._build_drawing_toolbar(draw_tab)

        self._draw_canvas = DrawingCanvas(draw_tab, self._draw_doc)
        self._draw_canvas.pack(fill="both", expand=True, padx=4, pady=4)

        tk.Label(
            draw_tab,
            text="  Left-drag: draw   Middle/Ctrl+drag: pan   Scroll: zoom",
            bg=_DARK_BG, fg="#3a6a3a", font=("Monospace", 8),
        ).pack(anchor="w", padx=4)

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

        # Tab 3: Layers  (for the Draw canvas)
        layers_tab = tk.Frame(right_nb, bg=_DARK_BG)
        right_nb.add(layers_tab, text="Layers")

        self._layers_panel = LayersPanel(
            layers_tab,
            doc=self._draw_doc,
            on_change=self._on_layers_changed,
            on_active_change=self._on_active_layer_changed,
        )
        self._layers_panel.pack(fill="both", expand=True, padx=2, pady=2)

        # "Generate G-code" button (in Layers tab)
        _btn_g = dict(bg="#1a4a1a", fg="#ccffcc",
                      activebackground="#2a6a2a", activeforeground="#ffffff",
                      relief="flat", padx=8, pady=3,
                      font=_MONO_SM, cursor="hand2")
        gen_row = tk.Frame(layers_tab, bg=_DARK_BG)
        gen_row.pack(fill="x", padx=4, pady=(0, 4))
        tk.Button(gen_row, text="⇒ Generate G-code from drawing",
                  command=self._generate_gcode_from_drawing,
                  **_btn_g).pack(fill="x")
        tk.Button(gen_row, text="✕ Clear drawing",
                  command=self._clear_drawing,
                  bg="#4a1a1a", fg="#ffcccc",
                  activebackground="#6a2a2a", activeforeground="#ffffff",
                  relief="flat", padx=8, pady=3,
                  font=_MONO_SM, cursor="hand2").pack(fill="x", pady=(2, 0))

        # Tab 4: 3-D Simulation
        sim_tab = tk.Frame(right_nb, bg=_DARK_BG)
        right_nb.add(sim_tab, text="Simulate")

        tk.Label(sim_tab, text="3-D ENGRAVE SIMULATION", bg=_DARK_BG,
                 fg="#4a9a4a", font=_MONO_SM).pack(anchor="w", padx=4, pady=(4, 0))

        self._sim_canvas = SimulationCanvas(sim_tab)
        self._sim_canvas.pack(fill="both", expand=True, padx=4, pady=4)

        sim_btn_row = tk.Frame(sim_tab, bg=_DARK_BG)
        sim_btn_row.pack(fill="x", padx=4, pady=2)
        _btn_s = dict(bg="#1a4a1a", fg="#ccffcc",
                      activebackground="#2a6a2a", activeforeground="#ffffff",
                      relief="flat", padx=8, pady=2, font=_MONO_SM, cursor="hand2")
        tk.Button(sim_btn_row, text="⟳ Re-Simulate",
                  command=self._run_simulation, **_btn_s).pack(side="left", padx=2)
        tk.Button(sim_btn_row, text="✗ Clear",
                  command=self._sim_canvas.clear, **_btn_s).pack(side="left", padx=2)

        # Tab 5: Job Queue
        self._queue_panel = JobQueuePanel(
            right_nb,
            queue=self._job_queue,
            on_run_all=self._run_queue_all,
            on_run_next=self._run_queue_next,
            get_gcode=lambda: self._editor.get("1.0", "end-1c"),
        )
        right_nb.add(self._queue_panel, text="Queue")

        # Tab 6: Cost Estimator
        self._cost_panel = CostPanel(
            right_nb,
            get_burn_path=lambda: list(self._machine.burn_path),
            get_feed_rate=lambda: self._machine.feed_rate,
        )
        right_nb.add(self._cost_panel, text="Cost")

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

        # ---- Tools ----
        tools_menu = tk.Menu(menubar, tearoff=False, bg="#0f2a0f",
                             fg="#ccffcc", activebackground="#1a4a1a",
                             activeforeground="#ffffff")
        tools_menu.add_command(label="Optimize Path (AI)…",
                               command=self._optimize_path)
        tools_menu.add_command(label="Estimate Job Cost",
                               command=self._open_cost_tab)
        tools_menu.add_separator()
        tools_menu.add_command(label="Gradient Fill…",
                               command=self._prompt_gradient_fill)
        tools_menu.add_command(label="Texture Fill…",
                               command=self._prompt_texture_fill)
        tools_menu.add_separator()
        tools_menu.add_command(label="Batch Queue",
                               command=self._open_queue_tab)
        tools_menu.add_separator()
        tools_menu.add_command(label="Reload Plugins",
                               command=self._reload_plugins)
        tools_menu.add_command(label="Plugin Info…",
                               command=self._show_plugin_info)
        menubar.add_cascade(label="Tools", menu=tools_menu)

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

        tk.Frame(parent, bg="#0f2a0f", width=2).pack(side="left", padx=6, fill="y")

        # --- COM port selector ---
        tk.Label(parent, text="PORT:", bg="#0f2a0f", fg="#7abf7a",
                 font=_MONO_SM).pack(side="left", padx=(2, 0))
        self._port_var = tk.StringVar(value="")
        self._port_cb = ttk.Combobox(
            parent, textvariable=self._port_var,
            values=self._list_serial_ports(),
            state="readonly", width=10,
            font=_MONO_SM,
        )
        self._port_cb.pack(side="left", padx=(2, 0))
        if self._port_cb["values"]:
            self._port_cb.current(0)
        tk.Button(parent, text="⟳", command=self._com_refresh,
                  bg="#0f2a0f", fg="#7abf7a",
                  activebackground="#1a4a1a", activeforeground="#ffffff",
                  relief="flat", padx=4, pady=2,
                  font=_MONO_SM, cursor="hand2").pack(side="left", padx=1)
        self._connect_btn = tk.Button(
            parent, text="Connect",
            command=self._com_connect,
            bg="#1a4a1a", fg="#ccffcc",
            activebackground="#2a6a2a", activeforeground="#ffffff",
            relief="flat", padx=6, pady=2,
            font=_MONO_SM, cursor="hand2",
        )
        self._connect_btn.pack(side="left", padx=(2, 4))
        self._com_status_var = tk.StringVar(value="●")
        self._com_status_lbl = tk.Label(
            parent, textvariable=self._com_status_var,
            bg="#0f2a0f", fg="#555555", font=_MONO_SM,
        )
        self._com_status_lbl.pack(side="left", padx=(0, 4))

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

    def _build_drawing_toolbar(self, parent: tk.Frame) -> None:
        """Build the tool-select row inside the Draw tab."""
        toolbar = tk.Frame(parent, bg="#0f2a0f", pady=3)
        toolbar.pack(fill="x", padx=4, pady=(4, 0))

        tk.Label(toolbar, text="TOOL:", bg="#0f2a0f", fg="#7abf7a",
                 font=_MONO_SM).pack(side="left", padx=(4, 2))

        tool_opts = dict(
            bg="#0f2a0f", fg="#7abf7a",
            activebackground="#1a4a1a", activeforeground="#ffffff",
            relief="flat", padx=8, pady=2,
            font=_MONO_SM, cursor="hand2",
            bd=0,
        )
        # Track active tool button for visual feedback
        self._draw_tool_buttons: dict = {}
        self._draw_tool_var = tk.StringVar(value="select")

        for key, label, tip in [
            ("select", "↖ Select",   "Click to select"),
            ("line",   "╱ Line",    "2-point line"),
            ("rect",   "▭ Rect",    "2-point rectangle"),
            ("circle", "○ Circle",  "2-point circle"),
            ("text",   "T Text",    "Click to place text"),
        ]:
            btn = tk.Button(
                toolbar, text=label,
                command=lambda k=key: self._set_draw_tool(k),
                **tool_opts,
            )
            btn.pack(side="left", padx=2)
            self._draw_tool_buttons[key] = btn

        tk.Frame(toolbar, bg="#0f2a0f", width=2).pack(
            side="left", padx=6, fill="y")

        tk.Button(toolbar, text="⊞ Fit",
                  command=lambda: self._draw_canvas.fit_all(),
                  **tool_opts).pack(side="left", padx=2)
        tk.Button(toolbar, text="🗑 Del selected",
                  command=self._delete_selected_draw_obj,
                  bg="#4a1a1a", fg="#ffcccc",
                  activebackground="#6a2a2a", activeforeground="#ffffff",
                  relief="flat", padx=8, pady=2,
                  font=_MONO_SM, cursor="hand2",
                  ).pack(side="left", padx=2)

        # Highlight default tool
        self._set_draw_tool("select")

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
        path = filedialog.askopenfilename(
            title="Import SVG",
            filetypes=[("SVG files", "*.svg"), ("All files", "*.*")],
        )
        if not path:
            return
        try:
            with open(path, "r", encoding="utf-8", errors="replace") as fh:
                source = fh.read()
        except OSError as exc:
            messagebox.showerror("SVG Import Error", str(exc), parent=self)
            return

        try:
            power = float(self._power_var.get())
        except ValueError:
            power = 500.0
        try:
            speed = float(self._feed_var.get())
        except ValueError:
            speed = 3000.0

        fname = os.path.basename(path)
        dlg = ImportParamsDialog(
            self, import_type="svg", filename=fname,
            default_power=power, default_speed=speed,
        )
        if dlg.result is None:
            return
        params = dlg.result
        power = params["power"]
        speed = params["speed"]

        try:
            gcode = self._apply_vector_toolpath(source, "svg", params, power, speed)
            self._editor.delete("1.0", "end")
            self._editor.insert("1.0", gcode)
            self._reset_machine()
            self._log.log(
                f"Imported SVG: {path}  "
                f"[{params['toolpath_type']}]"
            )
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
        except OSError as exc:
            messagebox.showerror("DXF Import Error", str(exc), parent=self)
            return

        try:
            power = float(self._power_var.get())
        except ValueError:
            power = 500.0
        try:
            speed = float(self._feed_var.get())
        except ValueError:
            speed = 3000.0

        fname = os.path.basename(path)
        dlg = ImportParamsDialog(
            self, import_type="dxf", filename=fname,
            default_power=power, default_speed=speed,
        )
        if dlg.result is None:
            return
        params = dlg.result
        power = params["power"]
        speed = params["speed"]

        try:
            gcode = self._apply_vector_toolpath(source, "dxf", params, power, speed)
            self._editor.delete("1.0", "end")
            self._editor.insert("1.0", gcode)
            self._reset_machine()
            self._log.log(
                f"Imported DXF: {path}  "
                f"[{params['toolpath_type']}]"
            )
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
            if path.lower().endswith(".bmp"):
                grid, img_w, img_h = load_bmp(path)
            else:
                grid, img_w, img_h = load_png_tkinter(path)
        except Exception as exc:  # noqa: BLE001
            messagebox.showerror("Image Import Error", str(exc), parent=self)
            return

        try:
            power = float(self._power_var.get())
        except ValueError:
            power = 500.0
        try:
            speed = float(self._feed_var.get())
        except ValueError:
            speed = 3000.0

        fname = os.path.basename(path)
        dlg = ImportParamsDialog(
            self, import_type="image", filename=fname,
            img_w=img_w, img_h=img_h,
            default_power=power, default_speed=speed,
        )
        if dlg.result is None:
            return
        params = dlg.result
        power = params["power"]
        speed = params["speed"]

        # Compute pixel_size from requested physical width
        pixel_size = 0.1
        if params["width_mm"] > 0 and img_w > 0:
            pixel_size = params["width_mm"] / img_w

        try:
            tp = params["toolpath_type"]
            if tp == "Image (Floyd-Steinberg Dither)":
                gcode = trace_image(
                    grid, mode="floyd-steinberg",
                    threshold=params["fs_threshold"],
                    power=power, speed=speed, pixel_size=pixel_size,
                )
            elif tp == "Image (Jarvis Dither)":
                gcode = trace_image(
                    grid, mode="jarvis",
                    threshold=params["jarvis_threshold"],
                    power=power, speed=speed, pixel_size=pixel_size,
                )
            elif tp == "Greyscale (Variable Power)":
                gcode = trace_image(
                    grid, mode="greyscale",
                    power=power, speed=speed, pixel_size=pixel_size,
                )
            elif tp == "Hatch Fill":
                from ..layer_effects import hatch_fill
                w_mm = (params["width_mm"] if params["width_mm"] > 0
                        else img_w * pixel_size)
                h_mm = (params["height_mm"] if params["height_mm"] > 0
                        else img_h * pixel_size)
                gcode = hatch_fill(
                    0, 0, w_mm, h_mm,
                    angle=params["angle"],
                    spacing=params["hatch_spacing"],
                    power=power, speed=speed,
                    crosshatch=params["crosshatch"],
                )
            else:
                # Fill (Raster Engraving) – default threshold raster
                gcode = trace_image(
                    grid, mode="threshold",
                    threshold=params["threshold"],
                    power=power, speed=speed, pixel_size=pixel_size,
                )
            self._editor.delete("1.0", "end")
            self._editor.insert("1.0", gcode)
            self._reset_machine()
            self._log.log(
                f"Imported image: {path}  ({img_w}×{img_h} px)  "
                f"[{tp}]"
            )
        except Exception as exc:  # noqa: BLE001
            messagebox.showerror("Image Import Error", str(exc), parent=self)

    # ------------------------------------------------------------------
    # Vector toolpath dispatcher (SVG / DXF)
    # ------------------------------------------------------------------

    def _apply_vector_toolpath(
        self,
        source: str,
        fmt: str,
        params: Dict,
        power: float,
        speed: float,
    ) -> str:
        """Parse *source* and apply the requested toolpath type.

        Returns the resulting G-code string.
        """
        from ..layer_effects import gradient_fill, hatch_fill, perforation_to_dashes, spiral_fill
        from ..design import offset_path, paths_to_gcode

        tp = params["toolpath_type"]

        # --- Parse to DesignPath objects ---
        paths = self._parse_vector_source(source, fmt, params, power, speed)

        # --- Compute bounding box of all paths ---
        def _bbox_all(ps):
            if not ps:
                return 0.0, 0.0, 100.0, 100.0
            all_pts = [pt for p in ps for pt in p.points]
            if not all_pts:
                return 0.0, 0.0, 100.0, 100.0
            xs = [p[0] for p in all_pts]
            ys = [p[1] for p in all_pts]
            return min(xs), min(ys), max(xs), max(ys)

        if tp == "Line (Cut)" or tp == "Knife/Drag":
            gcode = paths_to_gcode(paths, power, speed)

        elif tp == "Fill (Raster Engraving)":
            x0, y0, x1, y1 = _bbox_all(paths)
            gcode = gradient_fill(
                x0, y0, x1, y1,
                power_start=power, power_end=power,
                line_spacing=params["line_spacing"],
                speed=speed,
            )

        elif tp == "Offset Fill":
            result = []
            dist = params["offset_dist"]
            count = max(1, params["offset_count"])
            for p in paths:
                result.append(p)
                for i in range(1, count + 1):
                    result.append(offset_path(p, dist * i))
            gcode = paths_to_gcode(result, power, speed)

        elif tp == "Hatch Fill":
            x0, y0, x1, y1 = _bbox_all(paths)
            gcode = hatch_fill(
                x0, y0, x1, y1,
                angle=params["angle"],
                spacing=params["hatch_spacing"],
                power=power, speed=speed,
                crosshatch=params["crosshatch"],
            )

        elif tp == "Perforation (Dash/Score)":
            raw = paths_to_gcode(paths, power, speed)
            gcode = perforation_to_dashes(
                raw,
                dash_mm=params["dash_mm"],
                gap_mm=params["gap_mm"],
            )

        elif tp == "Greyscale (Variable Power)":
            # Treat as plain line cut (vector has no brightness data)
            gcode = paths_to_gcode(paths, power, speed)

        elif tp == "Spiral Toolpath":
            x0, y0, x1, y1 = _bbox_all(paths)
            cx = (x0 + x1) / 2.0
            cy = (y0 + y1) / 2.0
            gcode = spiral_fill(
                cx, cy,
                r_start=params["spiral_r_start"],
                r_end=params["spiral_r_end"],
                spacing=params["spiral_spacing"],
                power=power, speed=speed,
            )

        elif tp == "Optimization":
            optimized, result = self._optimizer.optimize(paths)
            gcode = paths_to_gcode(optimized, power, speed)
            self._log.log(
                f"Optimized: rapid {result.original_rapid_mm:.1f}mm → "
                f"{result.optimised_rapid_mm:.1f}mm "
                f"({result.rapid_saving_pct:.0f}% saved)"
            )

        else:
            gcode = paths_to_gcode(paths, power, speed)

        return gcode

    def _parse_vector_source(
        self,
        source: str,
        fmt: str,
        params: Dict,
        power: float,
        speed: float,
    ):
        """Parse SVG or DXF *source* into DesignPath objects with optional scaling."""
        if fmt == "svg":
            from ..importers.svg_importer import _collect_paths, _IDENTITY, _PX_TO_MM
            import xml.etree.ElementTree as _ET
            root = _ET.fromstring(source)
            paths = _collect_paths(root, _IDENTITY, _PX_TO_MM, power, speed, 1)
        else:
            from ..importers.dxf_importer import _parse_entities, _collect_multivalue
            from ..importers.dxf_importer import _entity_to_path
            from ..design import DesignPath
            entities = _parse_entities(source)
            paths = []
            for ent in entities:
                p = _entity_to_path(ent, power, speed, 1)
                if p is not None:
                    paths.append(p)
            paths.extend(_collect_multivalue(source, power, speed, 1))

        # Optional uniform scale to target width
        width_mm = params.get("width_mm", 0.0)
        if width_mm > 0 and paths:
            all_pts = [pt for p in paths for pt in p.points]
            if all_pts:
                xs = [pt[0] for pt in all_pts]
                ys = [pt[1] for pt in all_pts]
                cur_w = max(xs) - min(xs)
                if cur_w > 1e-6:
                    scale = width_mm / cur_w
                    for p in paths:
                        p.points = [(x * scale, y * scale)
                                    for x, y in p.points]
        return paths

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
    # Tools menu actions
    # ------------------------------------------------------------------

    def _optimize_path(self) -> None:
        paths = self._current_paths()
        if not paths:
            messagebox.showinfo("Optimize", "No path found in editor.", parent=self)
            return
        try:
            power = float(self._power_var.get())
            speed = float(self._feed_var.get())
        except ValueError:
            power, speed = 500.0, 3000.0
        optimized, result = self._optimizer.optimize(paths)
        gcode = paths_to_gcode(optimized, power, speed)
        self._editor.delete("1.0", "end")
        self._editor.insert("1.0", gcode)
        self._log.log(
            f"Path optimized: rapid {result.original_rapid_mm:.1f}mm → "
            f"{result.optimised_rapid_mm:.1f}mm "
            f"({result.rapid_saving_pct:.0f}% saved)  "
            f"segments merged: {result.segments_merged}"
        )

    def _open_cost_tab(self) -> None:
        """Switch the right notebook to the Cost tab."""
        parent = self._cost_panel.master
        if isinstance(parent, ttk.Notebook):
            idx = parent.index(self._cost_panel)
            parent.select(idx)

    def _open_queue_tab(self) -> None:
        """Switch the right notebook to the Queue tab."""
        parent = self._queue_panel.master
        if isinstance(parent, ttk.Notebook):
            idx = parent.index(self._queue_panel)
            parent.select(idx)

    def _prompt_gradient_fill(self) -> None:
        from ..layer_effects import gradient_fill
        dlg = tk.Toplevel(self)
        dlg.title("Gradient Fill")
        dlg.configure(bg="#0d1a0d")
        dlg.resizable(False, False)
        fields = [
            ("X start (mm)", "0.0"),
            ("Y start (mm)", "0.0"),
            ("X end (mm)", "40.0"),
            ("Y end (mm)", "40.0"),
            ("Power start (S)", "100"),
            ("Power end (S)", "1000"),
            ("Line spacing (mm)", "0.1"),
            ("Speed (mm/min)", "3000"),
        ]
        vars_ = []
        for i, (lbl, default) in enumerate(fields):
            tk.Label(dlg, text=lbl, bg="#0d1a0d", fg="#7abf7a",
                     font=_MONO_SM).grid(row=i, column=0, sticky="w", padx=8, pady=2)
            v = tk.StringVar(value=default)
            tk.Entry(dlg, textvariable=v, bg="#071407", fg="#00ff88",
                     font=_MONO_SM, width=10).grid(row=i, column=1, padx=8)
            vars_.append(v)

        def _ok():
            try:
                x0, y0 = float(vars_[0].get()), float(vars_[1].get())
                x1, y1 = float(vars_[2].get()), float(vars_[3].get())
                ps, pe = float(vars_[4].get()), float(vars_[5].get())
                sp, spd = float(vars_[6].get()), float(vars_[7].get())
            except ValueError:
                messagebox.showerror("Error", "Invalid values.", parent=dlg)
                return
            dlg.destroy()
            gcode = gradient_fill(x0, y0, x1, y1,
                                  power_start=ps, power_end=pe,
                                  line_spacing=sp, speed=spd)
            self._editor.delete("1.0", "end")
            self._editor.insert("1.0", gcode)
            self._log.log(f"Gradient fill {x0},{y0}→{x1},{y1}")

        tk.Button(dlg, text="OK", command=_ok,
                  bg="#1a4a1a", fg="#ccffcc", font=_MONO_SM).grid(
            row=len(fields), column=0, columnspan=2, pady=8)

    def _prompt_texture_fill(self) -> None:
        from ..layer_effects import texture_fill
        dlg = tk.Toplevel(self)
        dlg.title("Texture Fill")
        dlg.configure(bg="#0d1a0d")
        dlg.resizable(False, False)
        fields = [
            ("X start (mm)", "0.0"),
            ("Y start (mm)", "0.0"),
            ("X end (mm)", "40.0"),
            ("Y end (mm)", "40.0"),
            ("Pitch (mm)", "1.0"),
            ("Power (S)", "500"),
            ("Speed (mm/min)", "3000"),
            ("Dot size (mm)", "0.2"),
        ]
        vars_ = []
        for i, (lbl, default) in enumerate(fields):
            tk.Label(dlg, text=lbl, bg="#0d1a0d", fg="#7abf7a",
                     font=_MONO_SM).grid(row=i, column=0, sticky="w", padx=8, pady=2)
            v = tk.StringVar(value=default)
            tk.Entry(dlg, textvariable=v, bg="#071407", fg="#00ff88",
                     font=_MONO_SM, width=10).grid(row=i, column=1, padx=8)
            vars_.append(v)

        pattern_var = tk.StringVar(value="dot")
        tk.Label(dlg, text="Pattern", bg="#0d1a0d", fg="#7abf7a",
                 font=_MONO_SM).grid(row=len(fields), column=0, sticky="w", padx=8)
        tk.OptionMenu(dlg, pattern_var, "dot", "line", "cross").grid(
            row=len(fields), column=1, padx=8, pady=2)

        def _ok():
            try:
                x0, y0 = float(vars_[0].get()), float(vars_[1].get())
                x1, y1 = float(vars_[2].get()), float(vars_[3].get())
                pitch = float(vars_[4].get())
                power = float(vars_[5].get())
                speed = float(vars_[6].get())
                dot_size = float(vars_[7].get())
            except ValueError:
                messagebox.showerror("Error", "Invalid values.", parent=dlg)
                return
            dlg.destroy()
            gcode = texture_fill(x0, y0, x1, y1, pattern=pattern_var.get(),
                                 pitch=pitch, power=power, speed=speed,
                                 dot_size=dot_size)
            self._editor.delete("1.0", "end")
            self._editor.insert("1.0", gcode)
            self._log.log(f"Texture fill {pattern_var.get()}")

        tk.Button(dlg, text="OK", command=_ok,
                  bg="#1a4a1a", fg="#ccffcc", font=_MONO_SM).grid(
            row=len(fields) + 1, column=0, columnspan=2, pady=8)

    def _reload_plugins(self) -> None:
        self._plugin_manager = PluginManager()
        count = self._plugin_manager.load_all()
        self._log.log(f"Plugins reloaded: {count} loaded.")

    def _show_plugin_info(self) -> None:
        info = self._plugin_manager.plugin_info()
        errors = self._plugin_manager.errors()
        if not info and not errors:
            msg = "No plugins loaded.\nPlace .py files in ~/.lazerem/plugins/"
        else:
            parts = [f"{p['name']} v{p['version']}"
                     + (f"\n  {p['description']}" if p["description"] else "")
                     for p in info]
            msg = "\n\n".join(parts) if parts else "No plugins."
            if errors:
                msg += "\n\nErrors:\n" + "\n".join(errors)
        messagebox.showinfo("Plugin Info", msg, parent=self)

    # ------------------------------------------------------------------
    # Simulation
    # ------------------------------------------------------------------

    def _run_simulation(self) -> None:
        self._sim_canvas.update_simulation(list(self._machine.burn_path))
        self._log.log("3-D simulation updated.")

    # ------------------------------------------------------------------
    # Error monitor callback
    # ------------------------------------------------------------------

    def _on_monitor_alert(self, alert) -> None:
        self.after(0, self._log.log,
                   f"⚠ [{alert.severity.upper()}] {alert.code}: {alert.message}")

    # ------------------------------------------------------------------
    # Job queue actions
    # ------------------------------------------------------------------

    def _run_queue_all(self) -> None:
        if self._run_thread and self._run_thread.is_alive():
            messagebox.showwarning("Busy", "A job is already running.", parent=self)
            return

        def _worker() -> None:
            for job, msgs in self._job_queue.run_all(self._machine):
                self.after(0, self._queue_panel.refresh)
                self.after(0, self._log.log,
                           f"Queue: {job.name} → {job.status} "
                           f"({job.elapsed:.1f}s)")
                for m in msgs:
                    self.after(0, self._log.log, m)
            self.after(0, self._refresh_panels)
            self.after(0, lambda: self._canvas.set_burn_path(
                list(self._machine.burn_path),
                self._machine.position.as_tuple()))

        self._run_thread = threading.Thread(target=_worker, daemon=True)
        self._run_thread.start()

    def _run_queue_next(self) -> None:
        if self._run_thread and self._run_thread.is_alive():
            messagebox.showwarning("Busy", "A job is already running.", parent=self)
            return

        def _worker() -> None:
            result = self._job_queue.run_next(self._machine)
            if result:
                job, msgs = result
                self.after(0, self._queue_panel.refresh)
                self.after(0, self._log.log,
                           f"Queue next: {job.name} → {job.status}")
                for m in msgs:
                    self.after(0, self._log.log, m)
            else:
                self.after(0, self._log.log, "Queue: no pending jobs.")
            self.after(0, self._refresh_panels)

        self._run_thread = threading.Thread(target=_worker, daemon=True)
        self._run_thread.start()

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
            self._error_monitor.start()
            messages = self._machine.run_program(source, on_block=_on_block)
            self._error_monitor.stop()
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
        # Auto-update simulation
        self._sim_canvas.update_simulation(list(self._machine.burn_path))

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
    # Drawing tool actions
    # ------------------------------------------------------------------

    def _set_draw_tool(self, tool: str) -> None:
        """Activate a drawing tool and update toolbar button highlights."""
        self._draw_tool_var.set(tool)
        self._draw_canvas.tool = tool
        # Visual feedback: highlight active tool button
        for key, btn in self._draw_tool_buttons.items():
            if key == tool:
                btn.config(bg="#1a4a1a", fg="#00ff88", relief="sunken")
            else:
                btn.config(bg="#0f2a0f", fg="#7abf7a", relief="flat")

    def _delete_selected_draw_obj(self) -> None:
        """Remove the currently selected drawing object."""
        obj = self._draw_canvas._selected
        if obj is not None:
            self._draw_doc.remove_object(obj)
            self._draw_canvas._selected = None
            self._draw_canvas.redraw()
        else:
            self._log.log("No object selected in drawing canvas.")

    def _on_layers_changed(self) -> None:
        """Called by LayersPanel when layers are modified."""
        self._draw_canvas.redraw()

    def _on_active_layer_changed(self, idx: int) -> None:
        """Called by LayersPanel when the active layer selection changes."""
        self._draw_canvas.active_layer = idx

    def _generate_gcode_from_drawing(self) -> None:
        """Convert the current drawing to G-code and load it in the editor."""
        gcode = drawing_to_gcode(self._draw_doc)
        self._editor.delete("1.0", "end")
        self._editor.insert("1.0", gcode)
        self._log.log("G-code generated from drawing. Press F5 to run.")

    def _clear_drawing(self) -> None:
        """Remove all drawing objects (keeps layers)."""
        self._draw_doc.objects.clear()
        self._draw_canvas._selected = None
        self._draw_canvas.redraw()
        self._log.log("Drawing cleared.")

    # ------------------------------------------------------------------
    # Help
    # ------------------------------------------------------------------

    def _show_about(self) -> None:
        messagebox.showinfo(
            "About Ray5W Laser Control",
            "Ray5W Laser Control\n"
            "Version 3.0.0\n\n"
            "GRBL-style G-code interpreter and burn-path visualiser\n"
            "for the Ray5W diode laser engraver.\n\n"
            "Design capabilities:\n"
            "  SVG / DXF import\n"
            "  PNG / BMP raster image tracing\n"
            "  Image brightness, contrast, saturation\n"
            "  Path offset (kerf compensation)\n"
            "  Array / grid tool\n"
            "  Auto-nesting (shelf algorithm)\n"
            "  Material library (JSON presets)\n"
            "  Gradient fill / Texture fill\n"
            "  AI path optimiser (nearest-neighbour TSP)\n\n"
            "Advanced features:\n"
            "  3-D engraving depth-map simulation\n"
            "  Batch job queue\n"
            "  Job cost estimator\n"
            "  Real-time error / thermal monitoring\n"
            "  Plugin / extension system\n\n"
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

    # ------------------------------------------------------------------
    # COM port helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _list_serial_ports() -> list:
        """Return a list of available serial port names.

        Attempts to use *pyserial* if installed; falls back to platform-
        specific device globs.
        """
        try:
            from serial.tools import list_ports as _lp
            return [p.device for p in _lp.comports()] or ["(none found)"]
        except ImportError:
            pass
        # Fallback: scan common port names / device files
        if sys.platform.startswith("win"):
            return [f"COM{i}" for i in range(1, 10)]
        if sys.platform.startswith("darwin"):
            ports = (
                glob.glob("/dev/cu.usbserial*")
                + glob.glob("/dev/cu.usbmodem*")
                + glob.glob("/dev/tty.usbserial*")
            )
        else:
            ports = (
                glob.glob("/dev/ttyUSB*")
                + glob.glob("/dev/ttyACM*")
                + glob.glob("/dev/ttyS[0-9]*")
            )
        return sorted(ports) or ["(none found)"]

    def _com_refresh(self) -> None:
        """Refresh the COM port dropdown."""
        ports = self._list_serial_ports()
        self._port_cb["values"] = ports
        if ports:
            cur = self._port_var.get()
            if cur not in ports:
                self._port_cb.current(0)
        self._log.log("COM port list refreshed.")

    def _com_connect(self) -> None:
        """Toggle connection state for the selected COM port."""
        port = self._port_var.get()
        if not port or port == "(none found)":
            messagebox.showwarning(
                "No Port", "Select a COM port first.", parent=self)
            return
        if self._com_connected:
            # Disconnect
            self._com_connected = False
            self._com_port = ""
            self._connect_btn.config(text="Connect")
            self._com_status_var.set("●")
            self._com_status_lbl.config(fg="#555555")
            self._log.log(f"Disconnected from {port}.")
        else:
            # Connect (simulated – no real serial in this build)
            self._com_connected = True
            self._com_port = port
            self._connect_btn.config(text="Disconnect")
            self._com_status_var.set("●")
            self._com_status_lbl.config(fg="#00ff88")
            self._log.log(
                f"Connected to {port}  "
                f"(simulation mode – install pyserial for hardware)."
            )
