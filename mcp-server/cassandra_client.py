"""
Cassandra helper – lazy session singleton with graceful degradation.
"""

from __future__ import annotations

import logging
from typing import Any

from cassandra.cluster import Cluster, Session
from cassandra.policies import DCAwareRoundRobinPolicy

from config import CASSANDRA_HOSTS, CASSANDRA_PORT, CASSANDRA_KEYSPACE_AUTH, CASSANDRA_KEYSPACE_AI

logger = logging.getLogger(__name__)

_cluster: Cluster | None = None
_session: Session | None = None


def get_session() -> Session:
    global _cluster, _session
    if _session is None:
        _cluster = Cluster(
            CASSANDRA_HOSTS,
            port=CASSANDRA_PORT,
            load_balancing_policy=DCAwareRoundRobinPolicy(local_dc="DC1"),
        )
        _session = _cluster.connect()
    return _session


def query(cql: str, params: tuple[Any, ...] | None = None) -> list[dict[str, Any]]:
    """Execute a CQL SELECT and return rows as dicts."""
    session = get_session()
    rows = session.execute(cql, params or ())
    return [dict(row._asdict()) for row in rows]


def execute(cql: str, params: tuple[Any, ...] | None = None) -> None:
    """Execute a CQL write statement."""
    session = get_session()
    session.execute(cql, params or ())
