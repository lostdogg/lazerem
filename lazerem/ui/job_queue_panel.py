"""Job queue panel for the Ray5W laser control UI."""

from __future__ import annotations

import tkinter as tk
from tkinter import ttk, simpledialog, messagebox
from typing import Callable, Optional

from ..job_queue import JobQueue, QueuedJob

_DARK_BG = "#0d1a0d"
_MONO_SM = ("Monospace", 9)
_BTN = dict(
    bg="#1a4a1a", fg="#ccffcc",
    activebackground="#2a6a2a", activeforeground="#ffffff",
    relief="flat", padx=6, pady=2, font=_MONO_SM, cursor="hand2",
)


class JobQueuePanel(tk.Frame):
    """Panel that displays the job queue and lets the user manage it.

    Parameters
    ----------
    parent:
        Parent widget.
    queue:
        Shared :class:`~lazerem.job_queue.JobQueue` instance.
    on_run_all:
        Callback invoked when the user presses *Run All*.
    on_run_next:
        Callback invoked when the user presses *Run Next*.
    get_gcode:
        Callable that returns the current editor G-code text.
    """

    def __init__(
        self,
        parent: tk.Widget,
        queue: JobQueue,
        on_run_all: Optional[Callable[[], None]] = None,
        on_run_next: Optional[Callable[[], None]] = None,
        get_gcode: Optional[Callable[[], str]] = None,
    ) -> None:
        super().__init__(parent, bg=_DARK_BG)
        self._queue = queue
        self._on_run_all = on_run_all
        self._on_run_next = on_run_next
        self._get_gcode = get_gcode

        self._build()
        self.refresh()

    # ------------------------------------------------------------------
    # Public
    # ------------------------------------------------------------------

    def refresh(self) -> None:
        """Rebuild the listbox from the current queue state."""
        self._lb.delete(0, "end")
        for job in self._queue.jobs:
            status_icon = {
                "pending": "○",
                "running": "▶",
                "done": "✓",
                "error": "✗",
                "skipped": "–",
            }.get(job.status, "?")
            label = (
                f"{status_icon}  {job.name}"
                + (f"  S{int(job.power)}" if job.power else "")
                + (f"  F{int(job.speed)}" if job.speed else "")
                + (f"  ×{job.passes}" if job.passes and job.passes > 1 else "")
            )
            self._lb.insert("end", label)
            if job.status == "done":
                self._lb.itemconfig("end", fg="#55ff55")
            elif job.status == "error":
                self._lb.itemconfig("end", fg="#ff5555")
            elif job.status == "running":
                self._lb.itemconfig("end", fg="#ffff55")

        count = len(self._queue)
        pending = self._queue.pending_count()
        self._info_var.set(f"{count} jobs  ({pending} pending)")

    # ------------------------------------------------------------------
    # UI construction
    # ------------------------------------------------------------------

    def _build(self) -> None:
        tk.Label(self, text="BATCH JOB QUEUE", bg=_DARK_BG,
                 fg="#4a9a4a", font=_MONO_SM).pack(anchor="w", padx=4, pady=(4, 2))

        # Listbox
        lb_frame = tk.Frame(self, bg=_DARK_BG)
        lb_frame.pack(fill="both", expand=True, padx=4, pady=2)

        sb = tk.Scrollbar(lb_frame)
        sb.pack(side="right", fill="y")

        self._lb = tk.Listbox(
            lb_frame,
            bg="#071407", fg="#99ff99",
            selectbackground="#1a4a1a",
            font=_MONO_SM, relief="flat",
            yscrollcommand=sb.set,
            height=8,
        )
        self._lb.pack(fill="both", expand=True)
        sb.config(command=self._lb.yview)

        # Info row
        self._info_var = tk.StringVar(value="0 jobs")
        tk.Label(self, textvariable=self._info_var, bg=_DARK_BG,
                 fg="#6a9a6a", font=_MONO_SM).pack(anchor="w", padx=4)

        # Buttons row 1
        r1 = tk.Frame(self, bg=_DARK_BG)
        r1.pack(fill="x", padx=4, pady=2)

        tk.Button(r1, text="+ Add Current", command=self._add_current,
                  **_BTN).pack(side="left", padx=2)
        tk.Button(r1, text="✗ Remove", command=self._remove_selected,
                  **_BTN).pack(side="left", padx=2)
        tk.Button(r1, text="↑", command=self._move_up,
                  **_BTN).pack(side="left", padx=1)
        tk.Button(r1, text="↓", command=self._move_down,
                  **_BTN).pack(side="left", padx=1)

        # Buttons row 2
        r2 = tk.Frame(self, bg=_DARK_BG)
        r2.pack(fill="x", padx=4, pady=2)

        tk.Button(r2, text="▶ Run Next", command=self._run_next,
                  **_BTN).pack(side="left", padx=2)
        tk.Button(r2, text="▶▶ Run All", command=self._run_all,
                  **_BTN).pack(side="left", padx=2)
        tk.Button(r2, text="⟳ Reset All", command=self._reset_all,
                  **_BTN).pack(side="left", padx=2)
        tk.Button(r2, text="✗ Clear", command=self._clear_queue,
                  **_BTN).pack(side="left", padx=2)

    # ------------------------------------------------------------------
    # Button handlers
    # ------------------------------------------------------------------

    def _add_current(self) -> None:
        gcode = self._get_gcode() if self._get_gcode else ""
        name = simpledialog.askstring(
            "Add Job", "Job name:", initialvalue=f"Job {len(self._queue) + 1}",
            parent=self,
        )
        if not name:
            return
        self._queue.add(QueuedJob(name=name, gcode=gcode))
        self.refresh()

    def _remove_selected(self) -> None:
        sel = self._lb.curselection()
        if not sel:
            return
        idx = sel[0]
        self._queue.remove(idx)
        self.refresh()

    def _move_up(self) -> None:
        sel = self._lb.curselection()
        if not sel:
            return
        idx = sel[0]
        if self._queue.move_up(idx):
            self.refresh()
            self._lb.selection_set(idx - 1)

    def _move_down(self) -> None:
        sel = self._lb.curselection()
        if not sel:
            return
        idx = sel[0]
        if self._queue.move_down(idx):
            self.refresh()
            self._lb.selection_set(idx + 1)

    def _run_next(self) -> None:
        if self._on_run_next:
            self._on_run_next()
        self.refresh()

    def _run_all(self) -> None:
        if self._on_run_all:
            self._on_run_all()
        self.refresh()

    def _reset_all(self) -> None:
        self._queue.reset_statuses()
        self.refresh()

    def _clear_queue(self) -> None:
        if messagebox.askyesno("Clear Queue", "Remove all jobs?", parent=self):
            self._queue.clear()
            self.refresh()
