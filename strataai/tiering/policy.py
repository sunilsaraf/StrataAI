"""Tiering policies that decide when and where to migrate files.

A :class:`TieringPolicy` is a callable that receives a
:class:`~strataai.tiering.tiers.StorageTier` list and a
:class:`~strataai.intelligence.analyzer.FileScore` and returns the
recommended destination tier (or ``None`` if no migration is needed).
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING

from strataai.tiering.tiers import StorageTier, TierLevel

if TYPE_CHECKING:
    from strataai.intelligence.analyzer import FileScore


class TieringPolicy(ABC):
    """Abstract base class for tiering policies."""

    @abstractmethod
    def recommend(self, score: FileScore, tiers: list[StorageTier]) -> StorageTier | None:
        """Return the recommended tier for a file or ``None`` to keep it as-is."""


class ThresholdPolicy(TieringPolicy):
    """Rule-based policy that uses access-score thresholds.

    Files with a normalised *heat score* above ``hot_threshold`` are
    promoted to the HOT tier; files below ``cold_threshold`` are demoted
    to the COLD tier; everything else stays on the WARM tier.

    Parameters
    ----------
    hot_threshold:
        Files with ``score.heat >= hot_threshold`` are promoted to HOT.
    cold_threshold:
        Files with ``score.heat < cold_threshold`` are demoted to COLD.
    """

    def __init__(self, hot_threshold: float = 0.7, cold_threshold: float = 0.2) -> None:
        if not (0.0 <= cold_threshold < hot_threshold <= 1.0):
            raise ValueError(
                "Thresholds must satisfy 0 ≤ cold_threshold < hot_threshold ≤ 1"
            )
        self.hot_threshold = hot_threshold
        self.cold_threshold = cold_threshold

    def recommend(self, score: FileScore, tiers: list[StorageTier]) -> StorageTier | None:
        tier_map = {t.level: t for t in tiers}

        if score.heat >= self.hot_threshold:
            target_level = TierLevel.HOT
        elif score.heat < self.cold_threshold:
            target_level = TierLevel.COLD
        else:
            target_level = TierLevel.WARM

        target = tier_map.get(target_level)
        if target is None:
            # Requested tier not configured – fall back gracefully
            return None
        if score.current_tier == target_level:
            # Already on the right tier
            return None
        if not target.has_room_for(score.size_bytes):
            # Not enough space – try the next best tier
            fallback_level = TierLevel.WARM if target_level == TierLevel.HOT else TierLevel.WARM
            return tier_map.get(fallback_level)
        return target
