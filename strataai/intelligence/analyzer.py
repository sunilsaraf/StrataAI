"""Access-pattern analyzer and AI-based tier predictor.

The :class:`PatternAnalyzer` records I/O events for each file, computes a
*heat score* (0.0 = ice-cold, 1.0 = white-hot) and returns a
:class:`FileScore` that the tiering engine uses to decide migrations.

Heat is calculated as a time-decayed access frequency::

    heat = min(1.0, access_count / normalization_factor * recency_weight)

where ``recency_weight = e^(-λ * age_seconds)`` with a configurable decay
constant λ.
"""

from __future__ import annotations

import math
import time
from collections import defaultdict
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from strataai.tiering.tiers import TierLevel

if TYPE_CHECKING:
    from strataai.lustre.connector import FileInfo


@dataclass(frozen=True)
class FileScore:
    """Immutable snapshot of a file's tiering score.

    Attributes
    ----------
    path:
        Absolute file path.
    heat:
        Normalised heat value in [0.0, 1.0].
    current_tier:
        The tier the file is believed to reside on at scoring time.
    size_bytes:
        File size used by the tiering engine for capacity calculations.
    access_count:
        Raw access count recorded since tracking started.
    """

    path: str
    heat: float
    current_tier: TierLevel
    size_bytes: int
    access_count: int


@dataclass
class PatternAnalyzer:
    """Tracks file access events and produces :class:`FileScore` objects.

    Parameters
    ----------
    decay_lambda:
        Exponential decay constant (per second).  Higher values make scores
        respond more quickly to changing access patterns.  Default: ``1e-5``
        (half-life ≈ 19 hours).
    normalization_factor:
        Access count that maps to a heat of 1.0 before recency weighting.
    pool_to_tier:
        Mapping from Lustre pool name → :class:`~strataai.tiering.tiers.TierLevel`
        so the analyzer knows which tier a file is currently on.
    """

    decay_lambda: float = 1e-5
    normalization_factor: float = 100.0
    pool_to_tier: dict[str, TierLevel] = field(default_factory=dict)

    # Internal state – keyed by file path
    _access_counts: dict[str, int] = field(default_factory=lambda: defaultdict(int), init=False)
    _last_access: dict[str, float] = field(default_factory=dict, init=False)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def record_access(self, path: str, timestamp: float | None = None) -> None:
        """Register an I/O event for *path*.

        Parameters
        ----------
        path:
            Absolute file path.
        timestamp:
            Unix timestamp of the event; defaults to ``time.time()``.
        """
        ts = timestamp if timestamp is not None else time.time()
        self._access_counts[path] += 1
        self._last_access[path] = ts

    def score(self, file_info: FileInfo) -> FileScore:
        """Compute a :class:`FileScore` for *file_info*.

        If the file has never been accessed via :meth:`record_access`, the
        analyzer falls back to the ``last_access_time`` embedded in
        *file_info* (which may come from the filesystem ``atime``).
        """
        path = file_info.path
        access_count = self._access_counts.get(path, 0)

        # Determine the age of the last access for recency weighting.
        last_seen = self._last_access.get(path, file_info.last_access_time or 0.0)
        age_seconds = max(0.0, time.time() - last_seen) if last_seen else float("inf")

        recency_weight = math.exp(-self.decay_lambda * age_seconds)
        raw_heat = access_count / self.normalization_factor * recency_weight
        heat = min(1.0, raw_heat)

        # Determine current tier from pool name
        current_tier = self.pool_to_tier.get(file_info.pool, TierLevel.WARM)

        return FileScore(
            path=path,
            heat=heat,
            current_tier=current_tier,
            size_bytes=file_info.size_bytes,
            access_count=access_count,
        )

    def bulk_record(self, events: list[tuple[str, float]]) -> None:
        """Record multiple ``(path, timestamp)`` events at once."""
        for path, ts in events:
            self.record_access(path, ts)

    def has_recorded_access(self, path: str) -> bool:
        """Return ``True`` if at least one I/O event has been recorded for *path*."""
        return path in self._access_counts

    def reset(self, path: str | None = None) -> None:
        """Clear access records.  Pass *path* to reset a single file."""
        if path is None:
            self._access_counts.clear()
            self._last_access.clear()
        else:
            self._access_counts.pop(path, None)
            self._last_access.pop(path, None)
