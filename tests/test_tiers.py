"""Tests for storage tier definitions."""

from __future__ import annotations

import pytest

from strataai.tiering.tiers import StorageTier, TierLevel


class TestTierLevel:
    def test_ordering(self) -> None:
        assert TierLevel.HOT < TierLevel.WARM < TierLevel.COLD

    def test_equality(self) -> None:
        assert TierLevel.WARM == TierLevel.WARM
        assert TierLevel.HOT != TierLevel.COLD


class TestStorageTier:
    def test_defaults(self) -> None:
        tier = StorageTier(level=TierLevel.HOT, pool="hot")
        assert tier.used_bytes == 0
        assert tier.usage_fraction == 0.0

    def test_has_room_for_unlimited(self) -> None:
        tier = StorageTier(level=TierLevel.COLD, pool="cold", capacity_bytes=0)
        assert tier.has_room_for(10**12)

    def test_has_room_for_with_capacity(self) -> None:
        tier = StorageTier(level=TierLevel.HOT, pool="hot", capacity_bytes=1000)
        assert tier.has_room_for(500)
        tier.record_usage(800)
        assert not tier.has_room_for(500)
        assert tier.has_room_for(200)

    def test_record_usage_negative_delta(self) -> None:
        tier = StorageTier(level=TierLevel.WARM, pool="warm", capacity_bytes=1000)
        tier.record_usage(500)
        tier.record_usage(-200)
        assert tier.used_bytes == 300

    def test_usage_never_negative(self) -> None:
        tier = StorageTier(level=TierLevel.WARM, pool="warm", capacity_bytes=1000)
        tier.record_usage(-999)
        assert tier.used_bytes == 0

    def test_usage_fraction(self) -> None:
        tier = StorageTier(level=TierLevel.HOT, pool="hot", capacity_bytes=1000)
        tier.record_usage(250)
        assert tier.usage_fraction == pytest.approx(0.25)

    def test_free_bytes(self) -> None:
        tier = StorageTier(level=TierLevel.HOT, pool="hot", capacity_bytes=1000)
        tier.record_usage(300)
        assert tier.free_bytes == 700

    def test_str(self) -> None:
        tier = StorageTier(level=TierLevel.HOT, pool="nvme")
        assert "HOT" in str(tier)
        assert "nvme" in str(tier)
