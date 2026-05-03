"""Entry point for the Ray5W laser control application."""

from __future__ import annotations

from .ui.app import App


def main() -> None:
    app = App()
    app.mainloop()
