"""Main application window for the Ray5W laser control."""

from __future__ import annotations

import threading
import tkinter as tk
from tkinter import filedialog, messagebox
from typing import Optional

from ..machine import LaserMachine
from .canvas import BurnPathCanvas
from .panels import CoordinatePanel, LaserStatusPanel, MessageLog


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
        self.geometry("1200x750")
        self.minsize(900, 600)

        self._machine = LaserMachine()
        self._run_thread: Optional[threading.Thread] = None

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

        # Main pane: left editor | centre canvas | right panels
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

        # --- Right: status panels ---
        right = tk.Frame(pane, bg=_DARK_BG)
        pane.add(right, minsize=200, width=250)

        self._coord_panel = CoordinatePanel(right)
        self._coord_panel.pack(fill="x", padx=4, pady=(4, 2))

        self._status_panel = LaserStatusPanel(right)
        self._status_panel.pack(fill="x", padx=4, pady=2)

        self._log = MessageLog(right)
        self._log.pack(fill="both", expand=True, padx=4, pady=2)

        # --- MDI bar ---
        self._build_mdi_bar()

    def _build_menu(self) -> None:
        menubar = tk.Menu(self, bg="#0f2a0f", fg="#ccffcc",
                          activebackground="#1a4a1a",
                          activeforeground="#ffffff")

        file_menu = tk.Menu(menubar, tearoff=False, bg="#0f2a0f",
                            fg="#ccffcc", activebackground="#1a4a1a",
                            activeforeground="#ffffff")
        file_menu.add_command(label="New", command=self._new_program,
                              accelerator="Ctrl+N")
        file_menu.add_command(label="Open…", command=self._open_file,
                              accelerator="Ctrl+O")
        file_menu.add_command(label="Save…", command=self._save_file,
                              accelerator="Ctrl+S")
        file_menu.add_separator()
        file_menu.add_command(label="Quit", command=self.quit,
                              accelerator="Ctrl+Q")
        menubar.add_cascade(label="File", menu=file_menu)

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
        menubar.add_cascade(label="Laser", menu=laser_menu)

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

        tk.Frame(parent, bg="#0f2a0f", width=2).pack(side="left", padx=6,
                                                       fill="y")

        tk.Button(parent, text="Open", command=self._open_file,
                  **btn_opts).pack(side="left", padx=2)
        tk.Button(parent, text="Save", command=self._save_file,
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
    # Actions
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
        self._machine.reset()
        self._log.clear()
        self._log.log("Executing program …")
        self._refresh_panels()

        def _worker():
            messages = self._machine.run_program(source)
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

    def _show_about(self) -> None:
        messagebox.showinfo(
            "About Ray5W Laser Control",
            "Ray5W Laser Control\n"
            "Version 1.0.0\n\n"
            "GRBL-style G-code interpreter and burn-path\n"
            "visualiser for the Ray5W diode laser engraver.\n\n"
            "Supported codes:\n"
            "  G0  – Rapid (laser off)\n"
            "  G1  – Linear cut/engrave\n"
            "  G2/G3 – Circular arcs\n"
            "  M3  – Laser on (constant power)\n"
            "  M4  – Laser on (dynamic power)\n"
            "  M5  – Laser off\n"
            "  S   – Power (0–1000)\n"
            "  F   – Feed rate (mm/min)\n\n"
            "Controls:\n"
            "  F5  – Run program\n"
            "  F6  – Stop / E-stop\n"
            "  F   – Fit burn path\n"
            "  Scroll wheel – Zoom\n"
            "  Drag – Pan",
            parent=self,
        )
