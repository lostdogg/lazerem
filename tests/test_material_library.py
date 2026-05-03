"""Tests for the material library."""

from __future__ import annotations

import json
import os
import tempfile

import pytest

from lazerem.material_library import MaterialLibrary, MaterialPreset, _BUILT_IN_PRESETS


class TestMaterialPreset:
    def test_defaults(self):
        p = MaterialPreset(name="Test")
        assert p.power == 500.0
        assert p.speed == 3000.0
        assert p.passes == 1
        assert p.mode == "cut"
        assert p.dithering == "none"

    def test_copy(self):
        p = MaterialPreset("A", power=700, speed=1500, passes=2)
        q = p.copy()
        assert q.name == "A"
        assert q.power == 700
        q.power = 100  # mutating copy should not affect original
        assert p.power == 700


class TestMaterialLibrary:
    def _tmp_library(self) -> tuple[MaterialLibrary, str]:
        fd, path = tempfile.mkstemp(suffix=".json")
        os.close(fd)
        os.unlink(path)  # library should create the file on save
        lib = MaterialLibrary(path=path)
        return lib, path

    def test_built_ins_loaded(self):
        lib, path = self._tmp_library()
        names = lib.names()
        for p in _BUILT_IN_PRESETS:
            assert p.name in names

    def test_get_existing(self):
        lib, _ = self._tmp_library()
        p = lib.get("Birch Ply 3mm")
        assert p is not None
        assert p.power == 900
        assert p.passes == 3

    def test_get_missing(self):
        lib, _ = self._tmp_library()
        assert lib.get("Nonexistent Material") is None

    def test_add_new(self):
        lib, _ = self._tmp_library()
        before = len(lib.presets)
        lib.add(MaterialPreset("Custom", power=600, speed=1200))
        assert len(lib.presets) == before + 1
        assert lib.get("Custom") is not None

    def test_add_replaces_existing(self):
        lib, _ = self._tmp_library()
        lib.add(MaterialPreset("Cardboard", power=999, speed=100))
        p = lib.get("Cardboard")
        assert p is not None
        assert p.power == 999

    def test_remove_existing(self):
        lib, _ = self._tmp_library()
        result = lib.remove("Cardboard")
        assert result is True
        assert lib.get("Cardboard") is None

    def test_remove_missing(self):
        lib, _ = self._tmp_library()
        result = lib.remove("Does Not Exist")
        assert result is False

    def test_save_and_reload(self):
        lib, path = self._tmp_library()
        lib.add(MaterialPreset("SaveTest", power=123, speed=456, passes=2))
        lib.save()
        assert os.path.exists(path)

        lib2 = MaterialLibrary(path=path)
        p = lib2.get("SaveTest")
        assert p is not None
        assert p.power == 123
        assert p.speed == 456
        assert p.passes == 2

        os.unlink(path)

    def test_load_merges_builtins(self):
        """Built-ins not in the user file should still appear."""
        lib, path = self._tmp_library()
        # Save only one custom preset
        lib2_data = {"materials": [{"name": "Only One", "power": 1, "speed": 1,
                                    "passes": 1, "mode": "cut", "dithering": "none"}]}
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w") as fh:
            json.dump(lib2_data, fh)
        lib3 = MaterialLibrary(path=path)
        # Built-ins should be present
        assert lib3.get("Birch Ply 3mm") is not None
        # User preset should also be present
        assert lib3.get("Only One") is not None
        os.unlink(path)

    def test_names_returns_list(self):
        lib, _ = self._tmp_library()
        names = lib.names()
        assert isinstance(names, list)
        assert len(names) >= len(_BUILT_IN_PRESETS)
