"""Tests for tiering policy and engine."""

from __future__ import annotations

import time

import pytest

from strataai.intelligence.analyzer import FileScore, PatternAnalyzer
from strataai.tiering.engine import TieringEngine
from strataai.tiering.policy import ThresholdPolicy
from strataai.tiering.tiers import StorageTier, TierLevel
from tests.conftest import FakeBackend, LustreConnector


class TestThresholdPolicy:
    def setup_method(self) -> None:
        self.tiers = [
            StorageTier(level=TierLevel.HOT, pool="hot", capacity_bytes=10 * 1024**3),
            StorageTier(level=TierLevel.WARM, pool="warm", capacity_bytes=100 * 1024**3),
            StorageTier(level=TierLevel.COLD, pool="cold", capacity_bytes=1000 * 1024**3),
        ]
        self.policy = ThresholdPolicy(hot_threshold=0.7, cold_threshold=0.2)

    def _score(self, heat: float, current: TierLevel, size_bytes: int = 1024) -> FileScore:
        return FileScore(
            path="/test/file",
            heat=heat,
            current_tier=current,
            size_bytes=size_bytes,
            access_count=10,
        )

    def test_hot_file_promoted(self) -> None:
        score = self._score(heat=0.9, current=TierLevel.WARM)
        result = self.policy.recommend(score, self.tiers)
        assert result is not None
        assert result.level == TierLevel.HOT

    def test_cold_file_demoted(self) -> None:
        score = self._score(heat=0.1, current=TierLevel.WARM)
        result = self.policy.recommend(score, self.tiers)
        assert result is not None
        assert result.level == TierLevel.COLD

    def test_warm_file_stays(self) -> None:
        score = self._score(heat=0.5, current=TierLevel.WARM)
        result = self.policy.recommend(score, self.tiers)
        assert result is None

    def test_already_on_correct_tier_returns_none(self) -> None:
        score = self._score(heat=0.9, current=TierLevel.HOT)
        result = self.policy.recommend(score, self.tiers)
        assert result is None

    def test_invalid_thresholds_raise(self) -> None:
        with pytest.raises(ValueError):
            ThresholdPolicy(hot_threshold=0.3, cold_threshold=0.7)

    def test_no_room_on_hot_fallback_to_warm(self) -> None:
        # Fill the HOT tier completely
        self.tiers[0].record_usage(self.tiers[0].capacity_bytes)
        score = self._score(heat=0.9, current=TierLevel.WARM, size_bytes=1024)
        result = self.policy.recommend(score, self.tiers)
        # Should fall back to WARM (same tier → returns warm tier object)
        assert result is not None
        assert result.level == TierLevel.WARM


class TestTieringEngine:
    def setup_method(self) -> None:
        self.backend = FakeBackend()
        self.connector = LustreConnector(
            mount_point="/lustre/scratch", backend=self.backend
        )
        self.tiers = [
            StorageTier(level=TierLevel.HOT, pool="hot", capacity_bytes=10 * 1024**3),
            StorageTier(level=TierLevel.WARM, pool="warm", capacity_bytes=100 * 1024**3),
            StorageTier(level=TierLevel.COLD, pool="cold", capacity_bytes=1000 * 1024**3),
        ]
        self.analyzer = PatternAnalyzer(
            pool_to_tier={"hot": TierLevel.HOT, "warm": TierLevel.WARM, "cold": TierLevel.COLD}
        )
        self.policy = ThresholdPolicy(hot_threshold=0.7, cold_threshold=0.2)
        self.engine = TieringEngine(
            connector=self.connector,
            tiers=self.tiers,
            policy=self.policy,
            analyzer=self.analyzer,
            dry_run=True,
        )

    def test_run_produces_migration_records_for_hot_files(self) -> None:
        self.backend.add_file("/lustre/scratch/hot_file.dat", size_bytes=512, pool="warm")
        # Record many recent accesses to push heat above 0.7
        now = time.time()
        for _ in range(80):
            self.analyzer.record_access("/lustre/scratch/hot_file.dat", now)
        records = self.engine.run("/lustre/scratch")
        assert len(records) == 1
        assert records[0].to_tier == TierLevel.HOT
        assert records[0].success

    def test_run_no_migration_for_neutral_files(self) -> None:
        self.backend.add_file("/lustre/scratch/neutral.dat", size_bytes=512, pool="warm")
        # 50 accesses – heat ≈ 0.5, stays warm
        now = time.time()
        for _ in range(50):
            self.analyzer.record_access("/lustre/scratch/neutral.dat", now)
        records = self.engine.run("/lustre/scratch")
        assert records == []

    def test_run_demotes_cold_file(self) -> None:
        # File on warm with no recent access → cold
        old_time = time.time() - 10_000_000  # ~115 days ago
        self.backend.add_file(
            "/lustre/scratch/old_file.dat",
            size_bytes=512,
            pool="warm",
            atime=old_time,
        )
        self.analyzer.record_access("/lustre/scratch/old_file.dat", old_time)
        records = self.engine.run("/lustre/scratch")
        assert len(records) == 1
        assert records[0].to_tier == TierLevel.COLD

    def test_dry_run_does_not_call_migrate(self) -> None:
        self.backend.add_file("/lustre/scratch/file.dat", size_bytes=512, pool="warm")
        now = time.time()
        for _ in range(80):
            self.analyzer.record_access("/lustre/scratch/file.dat", now)
        self.engine.run("/lustre/scratch")
        assert self.backend.migrate_calls == []

    def test_live_run_calls_migrate(self) -> None:
        engine = TieringEngine(
            connector=self.connector,
            tiers=self.tiers,
            policy=self.policy,
            analyzer=self.analyzer,
            dry_run=False,
        )
        self.backend.add_file("/lustre/scratch/live.dat", size_bytes=512, pool="warm")
        now = time.time()
        for _ in range(80):
            self.analyzer.record_access("/lustre/scratch/live.dat", now)
        engine.run("/lustre/scratch")
        assert len(self.backend.migrate_calls) == 1
        assert self.backend.migrate_calls[0] == ("/lustre/scratch/live.dat", "hot")

    def test_migration_history_accumulated(self) -> None:
        self.backend.add_file("/lustre/scratch/f1.dat", size_bytes=512, pool="warm")
        self.backend.add_file("/lustre/scratch/f2.dat", size_bytes=512, pool="warm")
        now = time.time()
        for path in ["/lustre/scratch/f1.dat", "/lustre/scratch/f2.dat"]:
            for _ in range(80):
                self.analyzer.record_access(path, now)
        self.engine.run("/lustre/scratch")
        assert len(self.engine.migration_history) == 2
