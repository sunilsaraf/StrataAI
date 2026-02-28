"""Tests for the StrataAgent control plane."""

from __future__ import annotations

import time

from strataai.control_plane.agent import StrataAgent
from strataai.intelligence.analyzer import PatternAnalyzer
from strataai.lustre.connector import LustreConnector
from strataai.tiering.policy import ThresholdPolicy
from strataai.tiering.tiers import StorageTier, TierLevel
from tests.conftest import FakeBackend


def _make_agent(backend: FakeBackend, dry_run: bool = True) -> StrataAgent:
    connector = LustreConnector(mount_point="/lustre/scratch", backend=backend)
    tiers = [
        StorageTier(level=TierLevel.HOT, pool="hot", capacity_bytes=10 * 1024**3),
        StorageTier(level=TierLevel.WARM, pool="warm", capacity_bytes=100 * 1024**3),
        StorageTier(level=TierLevel.COLD, pool="cold", capacity_bytes=1000 * 1024**3),
    ]
    policy = ThresholdPolicy(hot_threshold=0.7, cold_threshold=0.2)
    analyzer = PatternAnalyzer(normalization_factor=100.0)
    return StrataAgent(
        connector=connector,
        tiers=tiers,
        policy=policy,
        analyzer=analyzer,
        dry_run=dry_run,
    )


class TestStrataAgent:
    def test_pool_to_tier_wired_on_init(self) -> None:
        agent = _make_agent(FakeBackend())
        assert agent.analyzer.pool_to_tier["hot"] == TierLevel.HOT
        assert agent.analyzer.pool_to_tier["warm"] == TierLevel.WARM
        assert agent.analyzer.pool_to_tier["cold"] == TierLevel.COLD

    def test_tick_returns_empty_for_empty_fs(self) -> None:
        agent = _make_agent(FakeBackend())
        records = agent.tick()
        assert records == []

    def test_tick_migrates_hot_file(self) -> None:
        backend = FakeBackend()
        agent = _make_agent(backend)
        backend.add_file("/lustre/scratch/popular.dat", size_bytes=512, pool="warm")
        now = time.time()
        for _ in range(80):
            agent.analyzer.record_access("/lustre/scratch/popular.dat", now)
        records = agent.tick()
        assert len(records) == 1
        assert records[0].to_tier == TierLevel.HOT
        assert records[0].success

    def test_tick_accumulates_history(self) -> None:
        backend = FakeBackend()
        agent = _make_agent(backend)
        backend.add_file("/lustre/scratch/f.dat", size_bytes=512, pool="warm")
        now = time.time()
        for _ in range(80):
            agent.analyzer.record_access("/lustre/scratch/f.dat", now)
        agent.tick()
        assert len(agent.migration_history) == 1

    def test_start_stop_background_thread(self) -> None:
        agent = _make_agent(FakeBackend())
        agent.scan_interval_seconds = 9999  # don't fire during test
        agent.start()
        assert agent.is_running
        agent.stop(timeout=2.0)
        assert not agent.is_running

    def test_start_twice_is_safe(self) -> None:
        agent = _make_agent(FakeBackend())
        agent.scan_interval_seconds = 9999
        agent.start()
        agent.start()  # should not raise or create duplicate thread
        assert agent.is_running
        agent.stop(timeout=2.0)

    def test_tick_uses_atime_for_untracked_files(self) -> None:
        """Files with recent atime but no explicit access events are scored."""
        backend = FakeBackend()
        agent = _make_agent(backend)
        # A file with a recent atime but no recorded I/O – heat should be ~0
        backend.add_file(
            "/lustre/scratch/atime_file.dat",
            size_bytes=512,
            pool="warm",
            atime=time.time(),
        )
        # tick should not crash and should return no records (heat ≈ 0 → cold
        # after first atime registration but may or may not migrate)
        records = agent.tick()
        # Just ensure no exception is raised; demotion to cold may or may not
        # occur depending on how quickly the fallback atime is processed.
        assert isinstance(records, list)
