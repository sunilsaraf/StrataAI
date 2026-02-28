"""Cassandra metadata backend abstraction.

Provides a protocol-based abstraction over Apache Cassandra (or any
wide-column store) for persisting and querying object metadata and
bucket statistics.

In production a real ``cassandra-driver`` implementation would be plugged
in.  :class:`InMemoryCassandraBackend` provides a fully functional
in-memory implementation that requires no external services.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Protocol, runtime_checkable


@dataclass(frozen=True)
class ObjectMetadata:
    """Metadata record for a single storage object.

    Attributes
    ----------
    bucket:
        Name of the bucket (namespace) the object belongs to.
    key:
        Object key / path within the bucket.
    size_bytes:
        Object size in bytes.
    content_type:
        MIME type (e.g. ``application/octet-stream``).
    owner:
        User ID of the object owner.
    created_at:
        Unix timestamp when the object was created.
    last_modified:
        Unix timestamp of the most recent modification.
    tier:
        Current storage tier name (``hot``, ``warm``, or ``cold``).
    tags:
        Arbitrary key/value tags attached to the object.
    """

    bucket: str
    key: str
    size_bytes: int
    content_type: str = ""
    owner: str = ""
    created_at: float = 0.0
    last_modified: float = 0.0
    tier: str = "warm"
    tags: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class BucketStats:
    """Aggregated statistics for a storage bucket.

    Attributes
    ----------
    bucket:
        Bucket name.
    object_count:
        Total number of objects.
    total_bytes:
        Sum of all object sizes.
    hot_bytes:
        Bytes stored on the HOT tier.
    warm_bytes:
        Bytes stored on the WARM tier.
    cold_bytes:
        Bytes stored on the COLD tier.
    last_updated:
        Unix timestamp of the last stats update.
    """

    bucket: str
    object_count: int = 0
    total_bytes: int = 0
    hot_bytes: int = 0
    warm_bytes: int = 0
    cold_bytes: int = 0
    last_updated: float = 0.0


@runtime_checkable
class CassandraBackend(Protocol):
    """Protocol that any Cassandra-compatible backend must satisfy."""

    def get_object_metadata(self, bucket: str, key: str) -> ObjectMetadata | None: ...
    def put_object_metadata(self, meta: ObjectMetadata) -> None: ...
    def get_bucket_stats(self, bucket: str) -> BucketStats | None: ...
    def update_bucket_stats(self, stats: BucketStats) -> None: ...
    def list_objects(self, bucket: str) -> list[ObjectMetadata]: ...


class InMemoryCassandraBackend:
    """Fully in-memory Cassandra backend for testing and development."""

    def __init__(self) -> None:
        self._objects: dict[tuple[str, str], ObjectMetadata] = {}
        self._buckets: dict[str, BucketStats] = {}

    def get_object_metadata(self, bucket: str, key: str) -> ObjectMetadata | None:
        return self._objects.get((bucket, key))

    def put_object_metadata(self, meta: ObjectMetadata) -> None:
        self._objects[(meta.bucket, meta.key)] = meta

    def get_bucket_stats(self, bucket: str) -> BucketStats | None:
        return self._buckets.get(bucket)

    def update_bucket_stats(self, stats: BucketStats) -> None:
        self._buckets[stats.bucket] = stats

    def list_objects(self, bucket: str) -> list[ObjectMetadata]:
        return [m for (b, _), m in self._objects.items() if b == bucket]

    def recompute_bucket_stats(self, bucket: str) -> BucketStats:
        """Recompute and persist :class:`BucketStats` from stored objects."""
        objects = self.list_objects(bucket)
        stats = BucketStats(
            bucket=bucket,
            object_count=len(objects),
            total_bytes=sum(o.size_bytes for o in objects),
            hot_bytes=sum(o.size_bytes for o in objects if o.tier == "hot"),
            warm_bytes=sum(o.size_bytes for o in objects if o.tier == "warm"),
            cold_bytes=sum(o.size_bytes for o in objects if o.tier == "cold"),
            last_updated=time.time(),
        )
        self.update_bucket_stats(stats)
        return stats
