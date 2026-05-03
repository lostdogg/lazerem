"""Tests for lazerem.plugin_manager."""

from __future__ import annotations

import os
import tempfile
import pytest

from lazerem.plugin_manager import PluginManager, PluginRegistry


class TestPluginRegistry:
    def test_empty_registry(self):
        reg = PluginRegistry()
        assert reg.plugin_info() == []
        assert reg.hook_count("on_load") == 0

    def test_transform_gcode_passthrough(self):
        reg = PluginRegistry()
        result = reg.transform_gcode("G0 X0 Y0\nM2")
        assert result == "G0 X0 Y0\nM2"

    def test_dispatch_empty(self):
        reg = PluginRegistry()
        results = reg.dispatch("on_run_start", object())
        assert results == []


class TestPluginManager:
    def _write_plugin(self, directory: str, filename: str, code: str) -> str:
        path = os.path.join(directory, filename)
        with open(path, "w") as f:
            f.write(code)
        return path

    def test_load_from_empty_dir(self):
        with tempfile.TemporaryDirectory() as d:
            pm = PluginManager(plugin_dir=d)
            count = pm.load_all()
            assert count == 0
            assert pm.plugin_info() == []

    def test_load_from_nonexistent_dir(self):
        pm = PluginManager(plugin_dir="/tmp/nonexistent_xyz_abc_12345")
        count = pm.load_all()
        assert count == 0

    def test_load_valid_plugin(self):
        code = '''
PLUGIN_NAME = "Test Plugin"
PLUGIN_VERSION = "1.0"
PLUGIN_DESCRIPTION = "A test"

def on_load(registry):
    pass
'''
        with tempfile.TemporaryDirectory() as d:
            self._write_plugin(d, "test_p.py", code)
            pm = PluginManager(plugin_dir=d)
            count = pm.load_all()
            assert count == 1
            info = pm.plugin_info()
            assert len(info) == 1
            assert info[0]["name"] == "Test Plugin"
            assert info[0]["version"] == "1.0"

    def test_skip_file_without_plugin_name(self):
        code = 'x = 1\n'
        with tempfile.TemporaryDirectory() as d:
            self._write_plugin(d, "bad_plugin.py", code)
            pm = PluginManager(plugin_dir=d)
            count = pm.load_all()
            assert count == 0
            assert pm.errors()

    def test_skip_underscore_files(self):
        code = 'PLUGIN_NAME = "Hidden"\n'
        with tempfile.TemporaryDirectory() as d:
            self._write_plugin(d, "_private.py", code)
            pm = PluginManager(plugin_dir=d)
            count = pm.load_all()
            assert count == 0

    def test_plugin_with_syntax_error_skipped(self):
        code = 'PLUGIN_NAME = "Bad"\nthis is not valid python!!!'
        with tempfile.TemporaryDirectory() as d:
            self._write_plugin(d, "syntax_err.py", code)
            pm = PluginManager(plugin_dir=d)
            count = pm.load_all()
            assert count == 0
            assert pm.errors()

    def test_load_file_directly(self):
        code = 'PLUGIN_NAME = "Direct"\n'
        with tempfile.NamedTemporaryFile(
            suffix=".py", mode="w", delete=False
        ) as f:
            f.write(code)
            path = f.name
        try:
            pm = PluginManager()
            ok = pm.load_file(path)
            assert ok
            assert pm.plugin_info()[0]["name"] == "Direct"
        finally:
            os.unlink(path)

    def test_gcode_transform_hook(self):
        code = '''
PLUGIN_NAME = "Transformer"
def on_gcode_import(gcode):
    return gcode.replace("G0", "G1")
'''
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "transformer.py")
            with open(path, "w") as f:
                f.write(code)
            pm = PluginManager(plugin_dir=d)
            pm.load_all()
            result = pm.registry.transform_gcode("G0 X0 Y0\nG0 X10")
            assert "G1" in result
            assert "G0" not in result

    def test_multiple_plugins(self):
        code1 = 'PLUGIN_NAME = "A"\n'
        code2 = 'PLUGIN_NAME = "B"\n'
        with tempfile.TemporaryDirectory() as d:
            for i, code in enumerate([code1, code2]):
                with open(os.path.join(d, f"p{i}.py"), "w") as f:
                    f.write(code)
            pm = PluginManager(plugin_dir=d)
            count = pm.load_all()
            assert count == 2
