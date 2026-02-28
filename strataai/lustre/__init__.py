"""Lustre filesystem connector.

Provides an abstraction layer over Lustre HSM (Hierarchical Storage
Management) and ``lfs`` command-line utilities so that the rest of StrataAI
can be tested without a real Lustre mount point.
"""

from __future__ import annotations

import os
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol, runtime_checkable


@dataclass
class FileInfo:
    """Metadata about a file stored on Lustre."""

    path: str
    size_bytes: int
    stripe_count: int = 1
    stripe_size_bytes: int = 1_048_576  # 1 MiB default
    pool: str = ""
    last_access_time: float = 0.0
    last_modify_time: float = 0.0

    @property
    def size_mib(self) -> float:
        return self.size_bytes / (1024 * 1024)


@runtime_checkable
class LustreBackend(Protocol):
    """Protocol that any Lustre backend must satisfy.

    Real implementations talk to ``lfs``; test doubles can be simple stubs.
    """

    def stat(self, path: str) -> FileInfo: ...
    def setstripe(  # noqa: E501
        self, path: str, stripe_count: int, stripe_size_bytes: int, pool: str
    ) -> None: ...
    def migrate(self, path: str, target_pool: str) -> None: ...
    def list_files(self, directory: str) -> list[str]: ...


class LfsBackend:
    """Production backend that delegates to the ``lfs`` CLI tool."""

    def stat(self, path: str) -> FileInfo:
        stat_result = os.stat(path)
        stripe_info = self._lfs_getstripe(path)
        return FileInfo(
            path=path,
            size_bytes=stat_result.st_size,
            stripe_count=stripe_info.get("stripe_count", 1),
            stripe_size_bytes=stripe_info.get("stripe_size", 1_048_576),
            pool=stripe_info.get("pool", ""),
            last_access_time=stat_result.st_atime,
            last_modify_time=stat_result.st_mtime,
        )

    def setstripe(self, path: str, stripe_count: int, stripe_size_bytes: int, pool: str) -> None:
        cmd = ["lfs", "setstripe", "-c", str(stripe_count), "-S", str(stripe_size_bytes)]
        if pool:
            cmd += ["-p", pool]
        cmd.append(path)
        subprocess.run(cmd, check=True, capture_output=True)

    def migrate(self, path: str, target_pool: str) -> None:
        subprocess.run(
            ["lfs", "migrate", "-p", target_pool, path],
            check=True,
            capture_output=True,
        )

    def list_files(self, directory: str) -> list[str]:
        result = subprocess.run(
            ["lfs", "find", directory, "-type", "f"],
            check=True,
            capture_output=True,
            text=True,
        )
        return [line.strip() for line in result.stdout.splitlines() if line.strip()]

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _lfs_getstripe(self, path: str) -> dict:
        """Parse ``lfs getstripe`` output into a dict."""
        try:
            result = subprocess.run(
                ["lfs", "getstripe", path],
                check=True,
                capture_output=True,
                text=True,
            )
        except (subprocess.CalledProcessError, FileNotFoundError):
            return {}

        info: dict = {}
        for line in result.stdout.splitlines():
            line = line.strip()
            if line.startswith("stripe_count:"):
                info["stripe_count"] = int(line.split(":")[1].strip())
            elif line.startswith("stripe_size:"):
                info["stripe_size"] = int(line.split(":")[1].strip())
            elif line.startswith("pool:"):
                info["pool"] = line.split(":")[1].strip()
        return info


@dataclass
class LustreConnector:
    """High-level connector for a Lustre filesystem mount point.

    Parameters
    ----------
    mount_point:
        Absolute path to the Lustre mount (e.g. ``/lustre/scratch``).
    backend:
        Backend implementation.  Defaults to :class:`LfsBackend`.
    """

    mount_point: str
    backend: LustreBackend = field(default_factory=LfsBackend)

    def __post_init__(self) -> None:
        self._mount = Path(self.mount_point)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def is_available(self) -> bool:
        """Return ``True`` when the mount point is accessible."""
        return self._mount.is_dir()

    def get_file_info(self, path: str) -> FileInfo:
        """Retrieve metadata for *path* (absolute or relative to mount)."""
        resolved = self._resolve(path)
        return self.backend.stat(resolved)

    def set_file_stripe(
        self, path: str, stripe_count: int = 1, stripe_size_bytes: int = 1_048_576, pool: str = ""
    ) -> None:
        """Set Lustre striping parameters on *path*."""
        resolved = self._resolve(path)
        self.backend.setstripe(resolved, stripe_count, stripe_size_bytes, pool)

    def migrate_to_pool(self, path: str, pool: str) -> None:
        """Move *path* to the given OST pool (used during tier migration)."""
        resolved = self._resolve(path)
        self.backend.migrate(resolved, pool)

    def scan_directory(self, directory: str = "") -> list[FileInfo]:
        """Return :class:`FileInfo` for every file under *directory*."""
        target = self._resolve(directory) if directory else self.mount_point
        paths = self.backend.list_files(target)
        return [self.backend.stat(p) for p in paths]

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _resolve(self, path: str) -> str:
        p = Path(path)
        if p.is_absolute():
            return str(p)
        return str(self._mount / p)
