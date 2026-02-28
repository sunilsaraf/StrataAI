"""MCP (Model Context Protocol) tool definitions.

Implements the three core tool calls exposed by the Agent Orchestrator:

* :meth:`McpTools.getObjectMetadata` – retrieve metadata for a storage object.
* :meth:`McpTools.getBucketStats`    – retrieve aggregated stats for a bucket.
* :meth:`McpTools.getUserPolicy`     – retrieve the IAM policy for a user.

Every call returns an :class:`McpToolResult` so that the orchestrator can
inspect success/failure without catching exceptions itself.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from strataai.storage.cassandra import BucketStats, CassandraBackend, ObjectMetadata
from strataai.storage.iam import IamLayer, UserPolicy


@dataclass(frozen=True)
class McpToolResult:
    """Immutable result returned by every MCP tool call.

    Attributes
    ----------
    tool:
        Name of the tool that produced this result.
    success:
        ``True`` when the call completed without error.
    data:
        The payload – an :class:`~strataai.storage.cassandra.ObjectMetadata`,
        :class:`~strataai.storage.cassandra.BucketStats`, or
        :class:`~strataai.storage.iam.UserPolicy` depending on the tool.
    error:
        Human-readable error description when ``success`` is ``False``.
    """

    tool: str
    success: bool
    data: Any = None
    error: str = ""


@dataclass
class McpTools:
    """Implements the three MCP tool calls used by the Agent Orchestrator.

    Parameters
    ----------
    cassandra:
        Storage backend for object metadata and bucket statistics.
    iam:
        IAM layer for user policy retrieval.
    """

    cassandra: CassandraBackend
    iam: IamLayer

    # ------------------------------------------------------------------
    # MCP tool call implementations
    # ------------------------------------------------------------------

    def getObjectMetadata(self, bucket: str, key: str) -> McpToolResult:  # noqa: N802
        """Retrieve metadata for the object at ``bucket/key``."""
        try:
            meta: ObjectMetadata | None = self.cassandra.get_object_metadata(bucket, key)
            if meta is None:
                return McpToolResult(
                    tool="getObjectMetadata",
                    success=False,
                    error=f"Object not found: {bucket}/{key}",
                )
            return McpToolResult(tool="getObjectMetadata", success=True, data=meta)
        except Exception as exc:  # noqa: BLE001
            return McpToolResult(tool="getObjectMetadata", success=False, error=str(exc))

    def getBucketStats(self, bucket: str) -> McpToolResult:  # noqa: N802
        """Retrieve aggregated statistics for *bucket*."""
        try:
            stats: BucketStats | None = self.cassandra.get_bucket_stats(bucket)
            if stats is None:
                return McpToolResult(
                    tool="getBucketStats",
                    success=False,
                    error=f"Bucket not found: {bucket}",
                )
            return McpToolResult(tool="getBucketStats", success=True, data=stats)
        except Exception as exc:  # noqa: BLE001
            return McpToolResult(tool="getBucketStats", success=False, error=str(exc))

    def getUserPolicy(self, user_id: str) -> McpToolResult:  # noqa: N802
        """Retrieve the IAM policy for *user_id*."""
        try:
            policy: UserPolicy = self.iam.get_user_policy(user_id)
            return McpToolResult(tool="getUserPolicy", success=True, data=policy)
        except Exception as exc:  # noqa: BLE001
            return McpToolResult(tool="getUserPolicy", success=False, error=str(exc))
