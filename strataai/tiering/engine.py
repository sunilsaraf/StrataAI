"""Tiering engine – orchestrates data movement between storage tiers.

The engine ties together the :class:`~strataai.lustre.LustreConnector`,
the :class:`~strataai.tiering.tiers.StorageTier` hierarchy and a
:class:`~strataai.tiering.policy.TieringPolicy` into a single
*migrate-if-needed* loop.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from strataai.tiering.tiers import StorageTier, TierLevel

if TYPE_CHECKING:
    from strataai.intelligence.analyzer import FileScore, PatternAnalyzer
    from strataai.lustre.connector import LustreConnector
    from strataai.tiering.policy import TieringPolicy

logger = logging.getLogger(__name__)


@dataclass
class MigrationRecord:
    """Audit record produced when a file is migrated."""

    path: str
    from_tier: TierLevel
    to_tier: TierLevel
    size_bytes: int
    success: bool
    error: str = ""


@dataclass
class TieringEngine:
    """Moves files between Lustre OST pools based on AI-driven scores.

    Parameters
    ----------
    connector:
        Live :class:`~strataai.lustre.LustreConnector` instance.
    tiers:
        Ordered list of :class:`~strataai.tiering.tiers.StorageTier` objects.
    policy:
        The :class:`~strataai.tiering.policy.TieringPolicy` that decides
        migration targets.
    analyzer:
        The :class:`~strataai.intelligence.analyzer.PatternAnalyzer` that
        scores files.
    dry_run:
        When ``True`` the engine logs intended migrations but does **not**
        invoke the Lustre connector.
    """

    connector: LustreConnector
    tiers: list[StorageTier]
    policy: TieringPolicy
    analyzer: PatternAnalyzer
    dry_run: bool = False

    _history: list[MigrationRecord] = field(default_factory=list, init=False, repr=False)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def run(self, directory: str = "") -> list[MigrationRecord]:
        """Scan *directory*, score every file and migrate those that need it.

        Returns the list of :class:`MigrationRecord` objects produced.
        """
        new_records: list[MigrationRecord] = []
        for file_info in self.connector.scan_directory(directory):
            score = self.analyzer.score(file_info)
            target = self.policy.recommend(score, self.tiers)
            if target is None:
                continue
            record = self._migrate(file_info.path, score, target)
            new_records.append(record)
            self._history.append(record)
        return new_records

    @property
    def migration_history(self) -> list[MigrationRecord]:
        """Return all migration records produced since engine creation."""
        return list(self._history)

    def tier_for_pool(self, pool: str) -> StorageTier | None:
        """Look up a tier by its pool name."""
        for tier in self.tiers:
            if tier.pool == pool:
                return tier
        return None

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _migrate(
        self,
        path: str,
        score: FileScore,
        target: StorageTier,
    ) -> MigrationRecord:
        from_level = score.current_tier
        record = MigrationRecord(
            path=path,
            from_tier=from_level,
            to_tier=target.level,
            size_bytes=score.size_bytes,
            success=False,
        )
        if self.dry_run:
            logger.info(
                "DRY-RUN migrate %s: %s → %s (heat=%.3f)",
                path,
                from_level.name,
                target.level.name,
                score.heat,
            )
            record.success = True
            return record

        try:
            self.connector.migrate_to_pool(path, target.pool)
            # Update capacity accounting
            source = self.tier_for_pool(
                next(
                    (t.pool for t in self.tiers if t.level == from_level),
                    "",
                )
            )
            if source:
                source.record_usage(-score.size_bytes)
            target.record_usage(score.size_bytes)
            record.success = True
            logger.info(
                "Migrated %s: %s → %s (heat=%.3f)",
                path,
                from_level.name,
                target.level.name,
                score.heat,
            )
        except Exception as exc:  # noqa: BLE001
            record.error = str(exc)
            logger.error("Migration failed for %s: %s", path, exc)

        return record
