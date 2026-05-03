"""Plugin manager for the Ray5W laser control.

Discovers and loads third-party Python plugins from a *plugins* directory
(default ``~/.lazerem/plugins/``).

Plugin protocol
---------------
Each plugin is a Python ``.py`` file.  It may define any of the following
module-level attributes / callables which the host will call at the
appropriate times:

* ``PLUGIN_NAME: str``  – human-readable name (required)
* ``PLUGIN_VERSION: str`` – version string (optional)
* ``PLUGIN_DESCRIPTION: str`` – one-line description (optional)
* ``on_load(registry)``  – called once when the plugin is loaded.
  *registry* is the :class:`PluginRegistry` instance.
* ``on_run_start(machine)`` – called before every program run.
* ``on_run_end(machine, messages)`` – called after every program run.
* ``on_gcode_import(gcode: str) -> str`` – transform G-code text.
* ``on_block(index, block)`` – called for every executed G-code block.

Example plugin ``~/.lazerem/plugins/my_logger.py``::

    PLUGIN_NAME = "My Logger"
    PLUGIN_VERSION = "1.0"

    def on_load(registry):
        print("My Logger loaded")

    def on_run_start(machine):
        print(f"Run started – pass_count={machine.pass_count}")
"""

from __future__ import annotations

import importlib.util
import os
import traceback
from typing import Any, Callable, Dict, List, Optional


_DEFAULT_PLUGIN_DIR = os.path.join(os.path.expanduser("~"), ".lazerem", "plugins")


# ---------------------------------------------------------------------------
# Hook registry
# ---------------------------------------------------------------------------

class PluginRegistry:
    """Manages plugin hooks and dispatches calls to registered handlers."""

    # Supported hook names
    HOOKS = (
        "on_load",
        "on_run_start",
        "on_run_end",
        "on_gcode_import",
        "on_block",
    )

    def __init__(self) -> None:
        self._hooks: Dict[str, List[Callable]] = {h: [] for h in self.HOOKS}
        self._plugins: List[Dict[str, Any]] = []

    # ------------------------------------------------------------------
    # Internal registration (called by PluginManager)
    # ------------------------------------------------------------------

    def _register_plugin(self, module: Any) -> None:
        meta: Dict[str, Any] = {
            "name": getattr(module, "PLUGIN_NAME", module.__name__),
            "version": getattr(module, "PLUGIN_VERSION", "?"),
            "description": getattr(module, "PLUGIN_DESCRIPTION", ""),
            "module": module,
        }
        self._plugins.append(meta)
        for hook in self.HOOKS:
            fn = getattr(module, hook, None)
            if callable(fn):
                self._hooks[hook].append(fn)

    # ------------------------------------------------------------------
    # Public query
    # ------------------------------------------------------------------

    def plugin_info(self) -> List[Dict[str, str]]:
        """Return list of ``{name, version, description}`` dicts."""
        return [
            {
                "name": p["name"],
                "version": p["version"],
                "description": p["description"],
            }
            for p in self._plugins
        ]

    def hook_count(self, hook: str) -> int:
        """Return number of handlers registered for *hook*."""
        return len(self._hooks.get(hook, []))

    # ------------------------------------------------------------------
    # Dispatch helpers
    # ------------------------------------------------------------------

    def dispatch(self, hook: str, *args: Any, **kwargs: Any) -> List[Any]:
        """Call all handlers for *hook* with the given arguments.

        Returns a list of return values (skipping None).
        Exceptions from individual handlers are caught and printed to
        stderr to avoid crashing the host application.
        """
        results: List[Any] = []
        for fn in self._hooks.get(hook, []):
            try:
                rv = fn(*args, **kwargs)
                if rv is not None:
                    results.append(rv)
            except Exception:
                traceback.print_exc()
        return results

    def transform_gcode(self, gcode: str) -> str:
        """Apply all ``on_gcode_import`` transform hooks in order."""
        for fn in self._hooks.get("on_gcode_import", []):
            try:
                result = fn(gcode)
                if isinstance(result, str):
                    gcode = result
            except Exception:
                traceback.print_exc()
        return gcode


# ---------------------------------------------------------------------------
# Plugin manager
# ---------------------------------------------------------------------------

class PluginManager:
    """Discovers and loads plugins from a directory.

    Parameters
    ----------
    plugin_dir:
        Path to the directory to scan for ``.py`` plugin files.
        Defaults to ``~/.lazerem/plugins/``.
    """

    def __init__(self, plugin_dir: str = _DEFAULT_PLUGIN_DIR) -> None:
        self.plugin_dir = plugin_dir
        self.registry = PluginRegistry()
        self._errors: List[str] = []

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def load_all(self) -> int:
        """Discover and load all plugins in :attr:`plugin_dir`.

        Returns the number of successfully loaded plugins.
        """
        self._errors = []
        if not os.path.isdir(self.plugin_dir):
            return 0

        loaded = 0
        for entry in sorted(os.listdir(self.plugin_dir)):
            if not entry.endswith(".py") or entry.startswith("_"):
                continue
            path = os.path.join(self.plugin_dir, entry)
            ok = self._load_file(path)
            if ok:
                loaded += 1
        return loaded

    def load_file(self, path: str) -> bool:
        """Load a single plugin file.  Returns ``True`` on success."""
        return self._load_file(path)

    def errors(self) -> List[str]:
        """Return load-time error messages from the last :meth:`load_all` call."""
        return list(self._errors)

    def plugin_info(self) -> List[Dict[str, str]]:
        """Return metadata for all loaded plugins."""
        return self.registry.plugin_info()

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _load_file(self, path: str) -> bool:
        name = os.path.splitext(os.path.basename(path))[0]
        spec = importlib.util.spec_from_file_location(f"lazerem_plugin_{name}", path)
        if spec is None or spec.loader is None:
            self._errors.append(f"Cannot load spec for {path}")
            return False
        try:
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)  # type: ignore[union-attr]
        except Exception as exc:
            self._errors.append(f"{path}: {exc}")
            traceback.print_exc()
            return False

        if not hasattr(module, "PLUGIN_NAME"):
            self._errors.append(f"{path}: missing PLUGIN_NAME – skipped")
            return False

        self.registry._register_plugin(module)
        # Fire on_load immediately
        on_load = getattr(module, "on_load", None)
        if callable(on_load):
            try:
                on_load(self.registry)
            except Exception:
                traceback.print_exc()
        return True
