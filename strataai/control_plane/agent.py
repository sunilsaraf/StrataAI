"""Agentic control plane – the top-level orchestrator for StrataAI.

:class:`StrataAgent` continuously monitors a Lustre filesystem, scores
files via the :class:`~strataai.intelligence.analyzer.PatternAnalyzer`,
and triggers the :class:`~strataai.tiering.engine.TieringEngine` on a
configurable schedule.

The agent follows a simple *observe → analyse → plan → act* loop, which
is the canonical skeleton of cognitive autonomous agents.
"""

from __future__ import annotations

import logging
import threading
from dataclasses import dataclass, field

from strataai.intelligence.analyzer import PatternAnalyzer
from strataai.lustre.connector import LustreConnector
from strataai.tiering.engine import MigrationRecord, TieringEngine
from strataai.tiering.policy import ThresholdPolicy, TieringPolicy
from strataai.tiering.tiers import StorageTier, TierLevel

logger = logging.getLogger(__name__)


def _default_tiers() -> list[StorageTier]:
    """Return a sensible three-tier default hierarchy."""
    return [
        StorageTier(level=TierLevel.HOT, pool="hot", stripe_count=4, stripe_size_bytes=4_194_304),
        StorageTier(level=TierLevel.WARM, pool="warm", stripe_count=2, stripe_size_bytes=1_048_576),
        StorageTier(level=TierLevel.COLD, pool="cold", stripe_count=1, stripe_size_bytes=1_048_576),
    ]


@dataclass
class StrataAgent:
    """Cognitive Agentic Storage Control Plane.

    Parameters
    ----------
    connector:
        Lustre filesystem connector.
    tiers:
        Storage tier hierarchy.  Defaults to hot/warm/cold with sensible
        Lustre pool names.
    policy:
        Tiering policy.  Defaults to :class:`~strataai.tiering.policy.ThresholdPolicy`.
    analyzer:
        Pattern analyzer used to score files.
    scan_interval_seconds:
        How often (in seconds) the agent scans the filesystem and triggers
        migration decisions.
    dry_run:
        When ``True`` no actual data movement occurs (useful for testing and
        capacity planning).
    """

    connector: LustreConnector
    tiers: list[StorageTier] = field(default_factory=_default_tiers)
    policy: TieringPolicy = field(default_factory=ThresholdPolicy)
    analyzer: PatternAnalyzer = field(default_factory=PatternAnalyzer)
    scan_interval_seconds: float = 3600.0
    dry_run: bool = False

    _engine: TieringEngine = field(init=False, repr=False)
    _thread: threading.Thread | None = field(default=None, init=False, repr=False)
    _stop_event: threading.Event = field(default_factory=threading.Event, init=False, repr=False)

    def __post_init__(self) -> None:
        # Wire up pool→tier mapping in the analyzer
        self.analyzer.pool_to_tier = {t.pool: t.level for t in self.tiers}
        self._engine = TieringEngine(
            connector=self.connector,
            tiers=self.tiers,
            policy=self.policy,
            analyzer=self.analyzer,
            dry_run=self.dry_run,
        )

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def start(self) -> None:
        """Start the background observation-analysis-migration loop."""
        if self._thread and self._thread.is_alive():
            logger.warning("StrataAgent is already running.")
            return
        self._stop_event.clear()
        self._thread = threading.Thread(
            target=self._run_loop,
            name="StrataAgent",
            daemon=True,
        )
        self._thread.start()
        logger.info(
            "StrataAgent started (interval=%ss, dry_run=%s).",
            self.scan_interval_seconds,
            self.dry_run,
        )

    def stop(self, timeout: float = 5.0) -> None:
        """Signal the background loop to stop and wait for it to finish."""
        self._stop_event.set()
        if self._thread:
            self._thread.join(timeout=timeout)
        logger.info("StrataAgent stopped.")

    @property
    def is_running(self) -> bool:
        return bool(self._thread and self._thread.is_alive())

    # ------------------------------------------------------------------
    # Observe → Analyse → Plan → Act
    # ------------------------------------------------------------------

    def tick(self, directory: str = "") -> list[MigrationRecord]:
        """Execute one full observe-analyse-plan-act cycle synchronously.

        Parameters
        ----------
        directory:
            Sub-directory of the Lustre mount to scan.  Defaults to the
            entire mount point.

        Returns
        -------
        list[MigrationRecord]
            Records of every migration attempted in this cycle.
        """
        logger.debug("StrataAgent tick: scanning %s", directory or self.connector.mount_point)

        # Observe – pull current file states from Lustre
        try:
            file_infos = self.connector.scan_directory(directory)
        except Exception as exc:  # noqa: BLE001
            logger.error("Scan failed: %s", exc)
            return []

        # Analyse – refresh access-time-based scores for any file we have
        # not seen explicit I/O events for
        for fi in file_infos:
            if not self.analyzer.has_recorded_access(fi.path):
                if fi.last_access_time:
                    self.analyzer.record_access(fi.path, fi.last_access_time)

        # Plan & Act – delegate to the tiering engine
        records = self._engine.run(directory)

        if records:
            logger.info(
                "StrataAgent tick complete: %d file(s) migrated, %d failed.",
                sum(1 for r in records if r.success),
                sum(1 for r in records if not r.success),
            )
        else:
            logger.debug("StrataAgent tick complete: no migrations needed.")

        return records

    @property
    def migration_history(self) -> list[MigrationRecord]:
        """Full migration history across all ticks."""
        return self._engine.migration_history

    # ------------------------------------------------------------------
    # Internal loop
    # ------------------------------------------------------------------

    def _run_loop(self) -> None:
        while not self._stop_event.is_set():
            try:
                self.tick()
            except Exception as exc:  # noqa: BLE001
                logger.error("Unhandled error in StrataAgent loop: %s", exc)
            self._stop_event.wait(timeout=self.scan_interval_seconds)
