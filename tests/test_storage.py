"""Tests for the storage layer: Cassandra backend and IAM layer."""

from __future__ import annotations

import time

import pytest

from strataai.storage.cassandra import BucketStats, InMemoryCassandraBackend, ObjectMetadata
from strataai.storage.iam import (
    IamLayer,
    InMemoryIamBackend,
    PolicyEffect,
    PolicyStatement,
    UserPolicy,
)

# ---------------------------------------------------------------------------
# Cassandra backend
# ---------------------------------------------------------------------------


class TestObjectMetadata:
    def test_defaults(self) -> None:
        meta = ObjectMetadata(bucket="b", key="k", size_bytes=1024)
        assert meta.tier == "warm"
        assert meta.content_type == ""
        assert meta.tags == {}

    def test_frozen(self) -> None:
        meta = ObjectMetadata(bucket="b", key="k", size_bytes=512)
        with pytest.raises(Exception):
            meta.tier = "hot"  # type: ignore[misc]


class TestBucketStats:
    def test_defaults(self) -> None:
        stats = BucketStats(bucket="proj")
        assert stats.object_count == 0
        assert stats.total_bytes == 0


class TestInMemoryCassandraBackend:
    def setup_method(self) -> None:
        self.backend = InMemoryCassandraBackend()

    def test_round_trip_object_metadata(self) -> None:
        meta = ObjectMetadata(bucket="test", key="data/file.h5", size_bytes=4096, tier="hot")
        self.backend.put_object_metadata(meta)
        retrieved = self.backend.get_object_metadata("test", "data/file.h5")
        assert retrieved == meta

    def test_get_missing_object_returns_none(self) -> None:
        assert self.backend.get_object_metadata("no-bucket", "no-key") is None

    def test_round_trip_bucket_stats(self) -> None:
        stats = BucketStats(bucket="proj", object_count=3, total_bytes=3000)
        self.backend.update_bucket_stats(stats)
        assert self.backend.get_bucket_stats("proj") == stats

    def test_get_missing_bucket_returns_none(self) -> None:
        assert self.backend.get_bucket_stats("ghost") is None

    def test_list_objects(self) -> None:
        for i in range(3):
            self.backend.put_object_metadata(
                ObjectMetadata(bucket="bkt", key=f"file{i}.dat", size_bytes=100 * (i + 1))
            )
        objects = self.backend.list_objects("bkt")
        assert len(objects) == 3

    def test_list_objects_empty_bucket(self) -> None:
        assert self.backend.list_objects("empty") == []

    def test_recompute_bucket_stats(self) -> None:
        for tier in ("hot", "warm", "cold"):
            self.backend.put_object_metadata(
                ObjectMetadata(bucket="mix", key=f"{tier}.dat", size_bytes=1000, tier=tier)
            )
        stats = self.backend.recompute_bucket_stats("mix")
        assert stats.object_count == 3
        assert stats.total_bytes == 3000
        assert stats.hot_bytes == 1000
        assert stats.warm_bytes == 1000
        assert stats.cold_bytes == 1000
        assert stats.last_updated == pytest.approx(time.time(), abs=2.0)


# ---------------------------------------------------------------------------
# IAM layer
# ---------------------------------------------------------------------------


class TestPolicyStatement:
    def test_exact_action_match(self) -> None:
        stmt = PolicyStatement(
            effect=PolicyEffect.ALLOW,
            actions=("s3:GetObject",),
            resources=("bucket/key",),
        )
        assert stmt.matches_action("s3:GetObject")
        assert not stmt.matches_action("s3:PutObject")

    def test_wildcard_action(self) -> None:
        stmt = PolicyStatement(
            effect=PolicyEffect.ALLOW,
            actions=("s3:*",),
            resources=("*",),
        )
        assert stmt.matches_action("s3:GetObject")
        assert stmt.matches_action("s3:DeleteObject")

    def test_star_resource_matches_all(self) -> None:
        stmt = PolicyStatement(
            effect=PolicyEffect.ALLOW,
            actions=("*",),
            resources=("*",),
        )
        assert stmt.matches_resource("anything/at/all")

    def test_prefix_resource_match(self) -> None:
        stmt = PolicyStatement(
            effect=PolicyEffect.ALLOW,
            actions=("s3:GetObject",),
            resources=("project/*",),
        )
        assert stmt.matches_resource("project/data/file.h5")
        assert not stmt.matches_resource("other/data/file.h5")


class TestUserPolicy:
    def test_empty_policy_denies_all(self) -> None:
        policy = UserPolicy(user_id="alice")
        assert not policy.is_allowed("s3:GetObject", "bucket/key")

    def test_allow_statement_permits(self) -> None:
        stmt = PolicyStatement(
            effect=PolicyEffect.ALLOW,
            actions=("s3:GetObject",),
            resources=("project/*",),
        )
        policy = UserPolicy(user_id="bob", statements=(stmt,))
        assert policy.is_allowed("s3:GetObject", "project/data.csv")
        assert not policy.is_allowed("s3:PutObject", "project/data.csv")

    def test_deny_overrides_allow(self) -> None:
        allow = PolicyStatement(
            effect=PolicyEffect.ALLOW,
            actions=("s3:*",),
            resources=("*",),
        )
        deny = PolicyStatement(
            effect=PolicyEffect.DENY,
            actions=("s3:DeleteObject",),
            resources=("*",),
        )
        policy = UserPolicy(user_id="carol", statements=(allow, deny))
        assert policy.is_allowed("s3:GetObject", "bucket/key")
        assert not policy.is_allowed("s3:DeleteObject", "bucket/key")


class TestIamLayer:
    def setup_method(self) -> None:
        self.backend = InMemoryIamBackend()
        self.layer = IamLayer(backend=self.backend)

    def test_unknown_user_returns_empty_policy(self) -> None:
        policy = self.layer.get_user_policy("unknown")
        assert policy.user_id == "unknown"
        assert len(policy.statements) == 0

    def test_check_permission_allowed(self) -> None:
        stmt = PolicyStatement(
            effect=PolicyEffect.ALLOW,
            actions=("s3:GetObject",),
            resources=("*",),
        )
        policy = UserPolicy(user_id="dave", statements=(stmt,))
        self.backend.put_user_policy(policy)
        assert self.layer.check_permission("dave", "s3:GetObject", "any/resource")

    def test_check_permission_denied(self) -> None:
        self.backend.put_user_policy(UserPolicy(user_id="eve"))
        assert not self.layer.check_permission("eve", "s3:GetObject", "any/resource")
