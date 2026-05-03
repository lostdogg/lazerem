"""Job cost estimator panel for the Ray5W laser control UI."""

from __future__ import annotations

import tkinter as tk
from tkinter import ttk
from typing import Callable, Optional

from ..cost_estimator import CostEstimator

_DARK_BG = "#0d1a0d"
_MONO_SM = ("Monospace", 9)
_MONO_MED = ("Monospace", 10)
_BTN = dict(
    bg="#1a4a1a", fg="#ccffcc",
    activebackground="#2a6a2a", activeforeground="#ffffff",
    relief="flat", padx=8, pady=2, font=_MONO_SM, cursor="hand2",
)


class CostPanel(tk.Frame):
    """Panel that estimates job time, material usage, and cost.

    Parameters
    ----------
    parent:
        Parent widget.
    get_burn_path:
        Callable that returns the current ``machine.burn_path``.
    get_feed_rate:
        Callable that returns the current feed rate (mm/min).
    """

    def __init__(
        self,
        parent: tk.Widget,
        get_burn_path: Optional[Callable] = None,
        get_feed_rate: Optional[Callable[[], float]] = None,
    ) -> None:
        super().__init__(parent, bg=_DARK_BG)
        self._get_burn_path = get_burn_path
        self._get_feed_rate = get_feed_rate
        self._build()

    # ------------------------------------------------------------------
    # UI construction
    # ------------------------------------------------------------------

    def _build(self) -> None:
        tk.Label(self, text="JOB COST ESTIMATOR", bg=_DARK_BG,
                 fg="#4a9a4a", font=_MONO_SM).pack(anchor="w", padx=4, pady=(4, 2))

        # Settings
        settings = tk.LabelFrame(self, text="Settings", bg=_DARK_BG,
                                 fg="#88cc88", font=_MONO_SM, padx=4, pady=4)
        settings.pack(fill="x", padx=4, pady=2)

        def _row(label: str, default: str, unit: str) -> tk.StringVar:
            row = tk.Frame(settings, bg=_DARK_BG)
            row.pack(fill="x", pady=1)
            tk.Label(row, text=f"{label}:", bg=_DARK_BG, fg="#88cc88",
                     font=_MONO_SM, width=20, anchor="w").pack(side="left")
            var = tk.StringVar(value=default)
            tk.Entry(row, textvariable=var, width=8,
                     bg="#071407", fg="#00ff88",
                     insertbackground="#00ff88",
                     font=_MONO_SM, relief="flat").pack(side="left")
            tk.Label(row, text=unit, bg=_DARK_BG, fg="#557755",
                     font=_MONO_SM).pack(side="left", padx=2)
            return var

        self._watts_var = _row("Machine power", "40", "W")
        self._kwh_var = _row("Cost / kWh", "0.15", "USD")
        self._mat_var = _row("Material / cm²", "0.05", "USD")
        self._beam_var = _row("Beam width", "0.1", "mm")
        self._rapid_var = _row("Rapid speed", "5000", "mm/min")

        # Currency
        cur_row = tk.Frame(settings, bg=_DARK_BG)
        cur_row.pack(fill="x", pady=1)
        tk.Label(cur_row, text="Currency:", bg=_DARK_BG, fg="#88cc88",
                 font=_MONO_SM, width=20, anchor="w").pack(side="left")
        self._currency_var = tk.StringVar(value="USD")
        tk.Entry(cur_row, textvariable=self._currency_var, width=6,
                 bg="#071407", fg="#00ff88",
                 insertbackground="#00ff88",
                 font=_MONO_SM, relief="flat").pack(side="left")

        # Estimate button
        tk.Button(self, text="Calculate Estimate",
                  command=self._calculate,
                  **_BTN).pack(padx=4, pady=4)

        # Result display
        self._result_text = tk.Text(
            self,
            bg="#071407", fg="#99ff99",
            font=("Monospace", 8),
            relief="flat", height=12, state="disabled",
            wrap="none",
        )
        self._result_text.pack(fill="both", expand=True, padx=4, pady=2)

    # ------------------------------------------------------------------
    # Action
    # ------------------------------------------------------------------

    def _calculate(self) -> None:
        def _flt(var: tk.StringVar, default: float) -> float:
            try:
                return float(var.get())
            except ValueError:
                return default

        estimator = CostEstimator(
            machine_watts=_flt(self._watts_var, 40.0),
            cost_per_kwh=_flt(self._kwh_var, 0.15),
            material_cost_per_cm2=_flt(self._mat_var, 0.05),
            rapid_speed=_flt(self._rapid_var, 5000.0),
            beam_width_mm=_flt(self._beam_var, 0.1),
            currency=self._currency_var.get() or "USD",
        )

        segments = self._get_burn_path() if self._get_burn_path else []
        feed = self._get_feed_rate() if self._get_feed_rate else 3000.0

        report = estimator.estimate(segments, feed_rate=feed)

        self._result_text.config(state="normal")
        self._result_text.delete("1.0", "end")
        self._result_text.insert("1.0", report.summary())
        self._result_text.config(state="disabled")
