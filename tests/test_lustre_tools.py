"""
Tests for MCP tool: lustre_stat and lustre_layout.
"""

import sys
import os
import tempfile
import stat

_MCP_DIR = os.path.normpath(os.path.join(os.path.dirname(__file__), "..", "mcp-server"))
for _name in ("config", "tool_lustre"):
    sys.modules.pop(_name, None)
if _MCP_DIR not in sys.path:
    sys.path.insert(0, _MCP_DIR)
else:
    sys.path.remove(_MCP_DIR)
    sys.path.insert(0, _MCP_DIR)

import tool_lustre


def test_lustre_stat_real_file(tmp_path, monkeypatch):
    monkeypatch.setenv("LUSTRE_MOUNT", str(tmp_path))
    import importlib
    import config as cfg
    importlib.reload(cfg)
    importlib.reload(tool_lustre)

    f = tmp_path / "testfile.bin"
    f.write_bytes(b"hello world")

    result = tool_lustre.lustre_stat(str(f))

    assert result["size_bytes"] == 11
    assert "mtime" in result
    assert "inode" in result


def test_lustre_stat_path_escape_rejected(tmp_path, monkeypatch):
    mount = tmp_path / "lustre"
    mount.mkdir()
    monkeypatch.setenv("LUSTRE_MOUNT", str(mount))

    import importlib
    import config as cfg
    importlib.reload(cfg)
    importlib.reload(tool_lustre)

    import pytest
    with pytest.raises(ValueError, match="escapes"):
        tool_lustre.lustre_stat("/etc/passwd")


def test_lustre_layout_no_lfs(tmp_path, monkeypatch):
    monkeypatch.setenv("LUSTRE_MOUNT", str(tmp_path))

    import importlib
    import config as cfg
    importlib.reload(cfg)
    importlib.reload(tool_lustre)

    f = tmp_path / "layout_test.bin"
    f.write_bytes(b"x")

    # lfs not available in test env – should return zeros gracefully
    result = tool_lustre.lustre_layout(str(f))
    assert "stripe_count" in result
    assert "osts" in result
