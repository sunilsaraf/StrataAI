"""Storage tier definitions for StrataAI.

Three canonical tiers model the performance/capacity trade-off found in
typical HPC storage hierarchies:

* **hot**  – NVMe / flash-backed OSTs, highest IOPS, lowest capacity
* **warm** – spinning-disk OSTs, balanced performance and capacity
* **cold** – tape / nearline object store, lowest cost, highest latency

Each tier maps to a named Lustre OST pool so that file placement can be
enforced via ``lfs setstripe -p <pool>``.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum, auto


class TierLevel(Enum):
    """Ordered performance/cost levels from fastest to slowest."""

    HOT = auto()
    WARM = auto()
    COLD = auto()

    def __lt__(self, other: TierLevel) -> bool:
        return self.value < other.value

    def __le__(self, other: TierLevel) -> bool:
        return self.value <= other.value

    def __gt__(self, other: TierLevel) -> bool:
        return self.value > other.value

    def __ge__(self, other: TierLevel) -> bool:
        return self.value >= other.value


@dataclass
class StorageTier:
    """Represents a single storage tier and its associated Lustre OST pool.

    Parameters
    ----------
    level:
        Performance level of this tier.
    pool:
        Name of the Lustre OST pool backing this tier.
    capacity_bytes:
        Total usable capacity of this tier in bytes (0 = unlimited / unknown).
    stripe_count:
        Default Lustre stripe count for files placed on this tier.
    stripe_size_bytes:
        Default Lustre stripe size for files placed on this tier.
    """

    level: TierLevel
    pool: str
    capacity_bytes: int = 0
    stripe_count: int = 1
    stripe_size_bytes: int = 1_048_576  # 1 MiB

    # Internal accounting – updated by the tiering engine.
    _used_bytes: int = field(default=0, init=False, repr=False)

    # ------------------------------------------------------------------
    # Capacity helpers
    # ------------------------------------------------------------------

    @property
    def used_bytes(self) -> int:
        return self._used_bytes

    @property
    def free_bytes(self) -> int:
        if self.capacity_bytes == 0:
            return 0  # Unknown/unlimited – treat as 0 free
        return max(0, self.capacity_bytes - self._used_bytes)

    @property
    def usage_fraction(self) -> float:
        """Fraction of capacity consumed (0.0–1.0).  Returns 0.0 if unknown."""
        if self.capacity_bytes == 0:
            return 0.0
        return self._used_bytes / self.capacity_bytes

    def has_room_for(self, size_bytes: int) -> bool:
        """Return ``True`` if this tier can accept *size_bytes* more data."""
        if self.capacity_bytes == 0:
            return True  # Unknown capacity – optimistically allow
        return self.free_bytes >= size_bytes

    def record_usage(self, delta_bytes: int) -> None:
        """Adjust the internally tracked usage by *delta_bytes* (may be negative)."""
        self._used_bytes = max(0, self._used_bytes + delta_bytes)

    # ------------------------------------------------------------------
    # Dunder helpers
    # ------------------------------------------------------------------

    def __str__(self) -> str:
        return f"StorageTier(level={self.level.name}, pool={self.pool!r})"
