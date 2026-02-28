"""
MCP Tools: lustre_stat + lustre_layout
Reads file stats and stripe layout from Lustre filesystem.
"""

from __future__ import annotations

import os
import subprocess
from typing import Any

from config import LUSTRE_MOUNT


def _safe_path(lustre_path: str) -> str:
    """Resolve and validate path stays within the Lustre mount."""
    resolved = os.path.realpath(lustre_path)
    mount = os.path.realpath(LUSTRE_MOUNT)
    if not resolved.startswith(mount):
        raise ValueError(f"Path escapes Lustre mount: {lustre_path!r}")
    return resolved


def lustre_stat(lustre_path: str) -> dict[str, Any]:
    """Return size/mtime/ctime/inode/uid/gid for a Lustre file."""
    path = _safe_path(lustre_path)
    st = os.stat(path)
    return {
        "size_bytes": st.st_size,
        "mtime": st.st_mtime,
        "ctime": st.st_ctime,
        "inode": st.st_ino,
        "uid": st.st_uid,
        "gid": st.st_gid,
    }


def lustre_layout(lustre_path: str) -> dict[str, Any]:
    """
    Return Lustre stripe layout via `lfs getstripe`.
    Falls back to empty values if lfs is unavailable (non-Lustre test env).
    """
    path = _safe_path(lustre_path)
    try:
        result = subprocess.run(
            ["lfs", "getstripe", "--yaml", path],
            capture_output=True,
            text=True,
            timeout=5,
        )
        # Minimal parsing: extract stripe_count, stripe_size, osts
        stripe_count = 1
        stripe_size = 0
        osts: list[str] = []
        for line in result.stdout.splitlines():
            line = line.strip()
            if line.startswith("stripe_count:"):
                stripe_count = int(line.split(":", 1)[1].strip())
            elif line.startswith("stripe_size:"):
                stripe_size = int(line.split(":", 1)[1].strip())
            elif line.startswith("l_ost_idx:"):
                osts.append(line.split(":", 1)[1].strip())
        return {"stripe_count": stripe_count, "stripe_size": stripe_size, "osts": osts}
    except (FileNotFoundError, subprocess.TimeoutExpired):
        # lfs not available (dev/test environment)
        return {"stripe_count": 0, "stripe_size": 0, "osts": []}
