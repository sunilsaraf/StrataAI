"""IAM (Identity and Access Management) layer.

Provides a lightweight RBAC-style policy engine.  Each user has a
:class:`UserPolicy` composed of :class:`PolicyStatement` rules.

Explicit ``DENY`` statements always take priority.  The default effect
for an unmatched action is ``DENY``.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Protocol, runtime_checkable


class PolicyEffect(Enum):
    """Whether a policy statement allows or denies an action."""

    ALLOW = "Allow"
    DENY = "Deny"


@dataclass(frozen=True)
class PolicyStatement:
    """A single allow/deny rule within an :class:`UserPolicy`.

    Attributes
    ----------
    effect:
        :attr:`PolicyEffect.ALLOW` or :attr:`PolicyEffect.DENY`.
    actions:
        List of action patterns (e.g. ``["s3:GetObject", "s3:*"]``).
        A trailing ``*`` acts as a wildcard.
    resources:
        List of resource patterns (e.g. ``["project-bucket/*"]``).
        A trailing ``*`` acts as a wildcard.
    """

    effect: PolicyEffect
    actions: tuple[str, ...]
    resources: tuple[str, ...]

    def matches_action(self, action: str) -> bool:
        return any(_glob_match(a, action) for a in self.actions)

    def matches_resource(self, resource: str) -> bool:
        return any(_glob_match(r, resource) for r in self.resources)


def _glob_match(pattern: str, value: str) -> bool:
    """Minimal glob matching: ``*`` matches everything; ``prefix*`` matches prefix."""
    if pattern == "*":
        return True
    if pattern.endswith("*"):
        return value.startswith(pattern[:-1])
    return pattern == value


@dataclass(frozen=True)
class UserPolicy:
    """IAM policy assigned to a user.

    Attributes
    ----------
    user_id:
        Unique identifier of the user.
    statements:
        Ordered list of :class:`PolicyStatement` rules evaluated left-to-right.
    roles:
        Symbolic role names attached to the user (informational).
    """

    user_id: str
    statements: tuple[PolicyStatement, ...] = field(default_factory=tuple)
    roles: tuple[str, ...] = field(default_factory=tuple)

    def is_allowed(self, action: str, resource: str) -> bool:
        """Return ``True`` if this policy permits *action* on *resource*.

        Explicit ``DENY`` always wins; default effect is ``DENY``.
        """
        allowed = False
        for stmt in self.statements:
            if stmt.matches_action(action) and stmt.matches_resource(resource):
                if stmt.effect == PolicyEffect.DENY:
                    return False
                allowed = True
        return allowed


@runtime_checkable
class IamBackend(Protocol):
    """Protocol for IAM policy storage backends."""

    def get_user_policy(self, user_id: str) -> UserPolicy | None: ...
    def put_user_policy(self, policy: UserPolicy) -> None: ...


@dataclass
class IamLayer:
    """Evaluates IAM policies for actions on resources.

    Parameters
    ----------
    backend:
        Storage backend for :class:`UserPolicy` records.
    """

    backend: IamBackend

    def get_user_policy(self, user_id: str) -> UserPolicy:
        """Return the policy for *user_id* (empty policy = deny all)."""
        policy = self.backend.get_user_policy(user_id)
        return policy if policy is not None else UserPolicy(user_id=user_id)

    def check_permission(self, user_id: str, action: str, resource: str) -> bool:
        """Return ``True`` if *user_id* may perform *action* on *resource*."""
        return self.get_user_policy(user_id).is_allowed(action, resource)


class InMemoryIamBackend:
    """In-memory IAM backend for testing and development."""

    def __init__(self) -> None:
        self._policies: dict[str, UserPolicy] = {}

    def get_user_policy(self, user_id: str) -> UserPolicy | None:
        return self._policies.get(user_id)

    def put_user_policy(self, policy: UserPolicy) -> None:
        self._policies[policy.user_id] = policy
