"""Audit entries for what Tenantly itself does to a business (no member's token to sign with)."""

from __future__ import annotations

from common.internal import call

from .periods import TENANTLY


def tenantly(tenant_id: object, action: str, target: str, actor: tuple[str, str] = TENANTLY) -> None:
    """Raises if identity can't record it, so the change rolls back with it.

    `actor` is the Tenantly admin who acted from the console; staff tools sign as Tenantly.
    """
    call(
        "identity",
        "POST",
        "/internal/audit",
        json={
            "tenantId": str(tenant_id),
            "actorId": actor[0],
            "actorName": actor[1],
            "action": action,
            "category": "billing",
            "target": target,
        },
    )
