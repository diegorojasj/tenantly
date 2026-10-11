"""Reading the audit trail, scoped to what the reader may see."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from ..models import AuditEvent
from . import ledger

if TYPE_CHECKING:
    from common.auth import TenantClaims

LIMIT = 500


def read(claims: TenantClaims, scope: str | None) -> dict[str, Any]:
    claims.demand("audit.view")
    focus = claims.focus(scope)
    at_home = focus == claims.home_scope_id
    rows = AuditEvent.objects.filter(tenant_id=claims.tenant_id).order_by("-seq")[: LIMIT * 4]
    events = [
        {
            "id": f"evt_{e.seq}",
            "at": e.at.isoformat(),
            "actor": e.actor_name,
            "actorId": e.actor_id,
            "action": e.action,
            "category": e.category,
            "target": e.target,
            "scopeId": e.scope_id or "",
            "scopeName": e.scope_name or "—",
            "ip": e.ip or "—",
            "hash": e.hash,
            "prevHash": e.prev_hash,
        }
        for e in rows
        # Business-wide entries (no node) show at the reader's home scope.
        if (e.scope_id and claims.within(e.scope_id, focus)) or (not e.scope_id and at_home)
    ][:LIMIT]
    intact, length, head = ledger.verify(claims.tenant_id)
    return {"events": events, "chain": {"length": length, "intact": intact, "head": head}}
