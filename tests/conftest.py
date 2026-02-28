"""Shared test fixtures for StrataAI test suite."""

from __future__ import annotations

import time
from typing import Any

import pytest

from strataai.lustre.connector import FileInfo, LustreConnector
from strataai.tiering.tiers import StorageTier, TierLevel

# ---------------------------------------------------------------------------
# Fake Lustre backend
# ---------------------------------------------------------------------------


class FakeBackend:
    """In-memory Lustre backend – no real filesystem required."""

    def __init__(self, files: dict[str, dict] | None = None) -> None:
        # files: {path: {size_bytes, stripe_count, stripe_size_bytes, pool, atime, mtime}}
        self._files: dict[str, dict] = files or {}
        self.migrate_calls: list[tuple[str, str]] = []
        self.setstripe_calls: list[tuple[str, Any, Any, str]] = []

    def add_file(
        self,
        path: str,
        size_bytes: int = 1024,
        pool: str = "warm",
        atime: float | None = None,
        stripe_count: int = 1,
        stripe_size_bytes: int = 1_048_576,
    ) -> None:
        self._files[path] = dict(
            size_bytes=size_bytes,
            stripe_count=stripe_count,
            stripe_size_bytes=stripe_size_bytes,
            pool=pool,
            atime=atime or time.time(),
            mtime=time.time(),
        )

    def stat(self, path: str) -> FileInfo:
        if path not in self._files:
            raise FileNotFoundError(path)
        f = self._files[path]
        return FileInfo(
            path=path,
            size_bytes=f["size_bytes"],
            stripe_count=f["stripe_count"],
            stripe_size_bytes=f["stripe_size_bytes"],
            pool=f["pool"],
            last_access_time=f["atime"],
            last_modify_time=f["mtime"],
        )

    def setstripe(self, path: str, stripe_count: int, stripe_size_bytes: int, pool: str) -> None:
        self.setstripe_calls.append((path, stripe_count, stripe_size_bytes, pool))
        if path in self._files:
            self._files[path]["pool"] = pool

    def migrate(self, path: str, target_pool: str) -> None:
        self.migrate_calls.append((path, target_pool))
        if path in self._files:
            self._files[path]["pool"] = target_pool

    def list_files(self, directory: str) -> list[str]:
        return [p for p in self._files if p.startswith(directory)]


# ---------------------------------------------------------------------------
# Pytest fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def backend() -> FakeBackend:
    return FakeBackend()


@pytest.fixture()
def connector(backend: FakeBackend) -> LustreConnector:
    return LustreConnector(mount_point="/lustre/scratch", backend=backend)


@pytest.fixture()
def default_tiers() -> list[StorageTier]:
    return [
        StorageTier(
            level=TierLevel.HOT,
            pool="hot",
            capacity_bytes=10 * 1024**3,  # 10 GiB
            stripe_count=4,
        ),
        StorageTier(
            level=TierLevel.WARM,
            pool="warm",
            capacity_bytes=100 * 1024**3,  # 100 GiB
            stripe_count=2,
        ),
        StorageTier(
            level=TierLevel.COLD,
            pool="cold",
            capacity_bytes=1000 * 1024**3,  # 1 TiB
            stripe_count=1,
        ),
    ]
