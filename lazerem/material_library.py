"""Material preset library for the Ray5W laser control.

Presets are stored as JSON in ``~/.lazerem/materials.json``.
Each preset records: name, power (S 0-1000), speed (F mm/min), passes,
mode ('cut' or 'engrave'), and dithering algorithm.

A set of built-in presets is always available; user presets are merged on
top and take precedence when names match.
"""

from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass
from typing import Dict, List, Optional


_DEFAULT_PATH = os.path.join(os.path.expanduser("~"), ".lazerem", "materials.json")


@dataclass
class MaterialPreset:
    """A named collection of laser settings for a specific material."""

    name: str
    power: float = 500.0        # S value 0–1000
    speed: float = 3000.0       # F value mm/min
    passes: int = 1
    mode: str = "cut"           # 'cut' or 'engrave'
    dithering: str = "none"     # 'none', 'threshold', 'floyd-steinberg', 'jarvis'

    def copy(self) -> "MaterialPreset":
        return MaterialPreset(
            self.name, self.power, self.speed,
            self.passes, self.mode, self.dithering,
        )


_BUILT_IN_PRESETS: List[MaterialPreset] = [
    MaterialPreset("Birch Ply 3mm",         power=900,  speed=600,  passes=3, mode="cut"),
    MaterialPreset("Birch Ply 3mm Engrave", power=400,  speed=4000, passes=1, mode="engrave"),
    MaterialPreset("MDF 3mm",               power=950,  speed=500,  passes=4, mode="cut"),
    MaterialPreset("Acrylic 3mm",           power=800,  speed=700,  passes=2, mode="cut"),
    MaterialPreset("Cardboard",             power=600,  speed=2000, passes=1, mode="cut"),
    MaterialPreset("Leather 2mm",           power=700,  speed=1200, passes=1, mode="cut"),
    MaterialPreset("Photo Engrave",         power=300,  speed=3000, passes=1, mode="engrave",
                   dithering="floyd-steinberg"),
    MaterialPreset("Anodised Aluminium",    power=1000, speed=400,  passes=1, mode="engrave"),
]


class MaterialLibrary:
    """Load, save, and manage material presets.

    Usage::

        lib = MaterialLibrary()
        preset = lib.get("Birch Ply 3mm")
        lib.add(MaterialPreset("My Material", power=700, speed=1500))
        lib.save()
    """

    def __init__(self, path: str = _DEFAULT_PATH) -> None:
        self._path = path
        self._presets: List[MaterialPreset] = [p.copy() for p in _BUILT_IN_PRESETS]
        self._load()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    @property
    def presets(self) -> List[MaterialPreset]:
        return list(self._presets)

    def names(self) -> List[str]:
        return [p.name for p in self._presets]

    def get(self, name: str) -> Optional[MaterialPreset]:
        """Return the preset with *name*, or ``None`` if not found."""
        for p in self._presets:
            if p.name == name:
                return p
        return None

    def add(self, preset: MaterialPreset) -> None:
        """Add or replace a preset (matched by name)."""
        for i, p in enumerate(self._presets):
            if p.name == preset.name:
                self._presets[i] = preset
                return
        self._presets.append(preset)

    def remove(self, name: str) -> bool:
        """Remove preset by name.  Returns ``True`` if it existed."""
        before = len(self._presets)
        self._presets = [p for p in self._presets if p.name != name]
        return len(self._presets) < before

    def save(self) -> None:
        """Persist the current preset list to disk."""
        os.makedirs(os.path.dirname(self._path), exist_ok=True)
        data = {"materials": [asdict(p) for p in self._presets]}
        with open(self._path, "w", encoding="utf-8") as fh:
            json.dump(data, fh, indent=2)

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _load(self) -> None:
        if not os.path.exists(self._path):
            return
        try:
            with open(self._path, "r", encoding="utf-8") as fh:
                data = json.load(fh)
            _fields = set(MaterialPreset.__dataclass_fields__)
            user_presets: List[MaterialPreset] = []
            for item in data.get("materials", []):
                kwargs: Dict = {k: item[k] for k in _fields if k in item}
                if "name" in kwargs:
                    user_presets.append(MaterialPreset(**kwargs))
            # Merge: keep built-ins that user hasn't overridden
            user_names = {p.name for p in user_presets}
            merged = [p.copy() for p in _BUILT_IN_PRESETS if p.name not in user_names]
            merged.extend(user_presets)
            self._presets = merged
        except (OSError, json.JSONDecodeError, TypeError, KeyError):
            pass  # keep built-in defaults
