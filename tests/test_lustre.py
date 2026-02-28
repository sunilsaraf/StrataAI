"""Tests for the Lustre connector layer."""

from __future__ import annotations

import pytest

from strataai.lustre.connector import FileInfo, LustreConnector
from tests.conftest import FakeBackend


class TestLustreConnector:
    def test_is_available_false_for_nonexistent_mount(self) -> None:
        connector = LustreConnector(
            mount_point="/no/such/mount",
            backend=FakeBackend(),
        )
        assert not connector.is_available()

    def test_get_file_info_absolute_path(
        self, connector: LustreConnector, backend: FakeBackend
    ) -> None:
        backend.add_file("/lustre/scratch/data/file1.dat", size_bytes=4096, pool="warm")
        info = connector.get_file_info("/lustre/scratch/data/file1.dat")
        assert isinstance(info, FileInfo)
        assert info.size_bytes == 4096
        assert info.pool == "warm"

    def test_get_file_info_relative_path(
        self, connector: LustreConnector, backend: FakeBackend
    ) -> None:
        backend.add_file("/lustre/scratch/data/file2.dat", size_bytes=2048, pool="hot")
        info = connector.get_file_info("data/file2.dat")
        assert info.size_bytes == 2048
        assert info.pool == "hot"

    def test_migrate_to_pool_updates_backend(
        self, connector: LustreConnector, backend: FakeBackend
    ) -> None:
        backend.add_file("/lustre/scratch/bigfile.dat", size_bytes=1_000_000, pool="warm")
        connector.migrate_to_pool("/lustre/scratch/bigfile.dat", "cold")
        assert ("/lustre/scratch/bigfile.dat", "cold") in backend.migrate_calls

    def test_scan_directory_returns_file_infos(
        self, connector: LustreConnector, backend: FakeBackend
    ) -> None:
        for i in range(3):
            backend.add_file(f"/lustre/scratch/project/file{i}.dat", size_bytes=i * 100 + 1)
        infos = connector.scan_directory("/lustre/scratch/project")
        assert len(infos) == 3
        paths = {fi.path for fi in infos}
        assert "/lustre/scratch/project/file0.dat" in paths

    def test_scan_empty_directory(self, connector: LustreConnector) -> None:
        infos = connector.scan_directory("/lustre/scratch/empty")
        assert infos == []

    def test_file_info_size_mib(self) -> None:
        fi = FileInfo(path="/x", size_bytes=2 * 1024 * 1024)
        assert fi.size_mib == pytest.approx(2.0)
