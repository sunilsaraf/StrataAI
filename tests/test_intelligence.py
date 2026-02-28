"""Tests for the AI-based pattern analyzer."""

from __future__ import annotations

import math
import time

import pytest

from strataai.intelligence.analyzer import PatternAnalyzer
from strataai.lustre.connector import FileInfo
from strataai.tiering.tiers import TierLevel


def _make_file_info(
    path: str = "/test/file.dat",
    size_bytes: int = 1024,
    pool: str = "warm",
    atime: float | None = None,
) -> FileInfo:
    return FileInfo(
        path=path,
        size_bytes=size_bytes,
        pool=pool,
        last_access_time=atime or time.time(),
        last_modify_time=time.time(),
    )


class TestPatternAnalyzer:
    def setup_method(self) -> None:
        self.analyzer = PatternAnalyzer(
            decay_lambda=1e-5,
            normalization_factor=100.0,
            pool_to_tier={"hot": TierLevel.HOT, "warm": TierLevel.WARM, "cold": TierLevel.COLD},
        )

    def test_score_no_accesses_returns_zero_heat(self) -> None:
        fi = _make_file_info(atime=0.0)  # no atime → infinite age
        score = self.analyzer.score(fi)
        assert score.heat == pytest.approx(0.0, abs=1e-6)

    def test_score_recent_accesses_high_heat(self) -> None:
        path = "/test/hot.dat"
        now = time.time()
        for _ in range(100):
            self.analyzer.record_access(path, now)
        fi = _make_file_info(path=path)
        score = self.analyzer.score(fi)
        assert score.heat == pytest.approx(1.0, abs=1e-3)

    def test_score_decays_over_time(self) -> None:
        path = "/test/decaying.dat"
        old = time.time() - 86400  # 1 day ago
        for _ in range(100):
            self.analyzer.record_access(path, old)
        fi = _make_file_info(path=path)
        score = self.analyzer.score(fi)
        expected_weight = math.exp(-1e-5 * 86400)
        assert score.heat == pytest.approx(expected_weight, rel=0.01)

    def test_score_uses_pool_for_current_tier(self) -> None:
        fi = _make_file_info(pool="hot")
        score = self.analyzer.score(fi)
        assert score.current_tier == TierLevel.HOT

    def test_score_unknown_pool_defaults_to_warm(self) -> None:
        fi = _make_file_info(pool="unknown_pool")
        score = self.analyzer.score(fi)
        assert score.current_tier == TierLevel.WARM

    def test_heat_capped_at_one(self) -> None:
        path = "/test/very_hot.dat"
        now = time.time()
        for _ in range(10_000):  # far above normalization factor
            self.analyzer.record_access(path, now)
        fi = _make_file_info(path=path)
        score = self.analyzer.score(fi)
        assert score.heat <= 1.0

    def test_bulk_record(self) -> None:
        now = time.time()
        events = [("/test/a.dat", now), ("/test/b.dat", now)]
        self.analyzer.bulk_record(events)
        assert self.analyzer.has_recorded_access("/test/a.dat")
        assert self.analyzer.has_recorded_access("/test/b.dat")

    def test_reset_single_file(self) -> None:
        path = "/test/reset_me.dat"
        self.analyzer.record_access(path)
        self.analyzer.reset(path)
        assert not self.analyzer.has_recorded_access(path)

    def test_reset_all(self) -> None:
        self.analyzer.record_access("/test/x.dat")
        self.analyzer.record_access("/test/y.dat")
        self.analyzer.reset()
        assert not self.analyzer.has_recorded_access("/test/x.dat")
        assert not self.analyzer.has_recorded_access("/test/y.dat")

    def test_file_score_is_frozen(self) -> None:
        fi = _make_file_info()
        score = self.analyzer.score(fi)
        with pytest.raises(Exception):  # frozen dataclass
            score.heat = 0.5  # type: ignore[misc]
