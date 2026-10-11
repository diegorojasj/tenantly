"""The tamper-evident audit trail: each entry's hash covers its content and the
previous entry's hash, so rewriting history breaks every later link."""

from __future__ import annotations

import hashlib
from typing import TYPE_CHECKING, Any

from django.db import transaction
from django.utils import timezone

from ..models import AuditEvent, Tenant

if TYPE_CHECKING:
    from datetime import datetime

GENESIS = "0" * 16


def _digest(prev_hash: str, at: datetime, actor_id: str, action: str, target: str, scope_id: str | None) -> str:
    body = f"{prev_hash}|{at.isoformat()}|{actor_id}|{action}|{target}|{scope_id or ''}"
    return hashlib.sha256(body.encode()).hexdigest()[:16]


def append(tenant_id: str, entry: dict[str, Any]) -> AuditEvent:
    """`entry` keys: actor_id, actor_name, action, category, target, scope_id, scope_name, ip."""
    with transaction.atomic():
        # Lock the tenant row: concurrent writers queue up, so links never fork.
        Tenant.objects.select_for_update().get(id=tenant_id)
        last = AuditEvent.objects.filter(tenant_id=tenant_id).order_by("-seq").first()
        prev_hash = last.hash if last else GENESIS
        at = timezone.now()
        return AuditEvent.objects.create(
            tenant_id=tenant_id,
            seq=(last.seq + 1) if last else 1,
            at=at,
            actor_id=entry["actor_id"],
            actor_name=entry["actor_name"],
            action=entry["action"],
            category=entry["category"],
            target=entry["target"][:300],
            scope_id=entry.get("scope_id"),
            scope_name=entry.get("scope_name", ""),
            ip=entry.get("ip", ""),
            prev_hash=prev_hash,
            hash=_digest(
                prev_hash, at, entry["actor_id"], entry["action"], entry["target"][:300], entry.get("scope_id")
            ),
        )


def verify(tenant_id: str) -> tuple[bool, int, str]:
    """Recompute every link. Returns (intact, length, head hash)."""
    prev = GENESIS
    count = 0
    for event in AuditEvent.objects.filter(tenant_id=tenant_id).order_by("seq").iterator():
        expected = _digest(prev, event.at, event.actor_id, event.action, event.target, event.scope_id)
        if event.prev_hash != prev or event.hash != expected:
            return False, count, prev
        prev = event.hash
        count += 1
    return True, count, prev if count else ""
