"""Notices to the business about its Tenantly plan: each one happens once, keyed.

The page words them from `kind` and `params` in the reader's language. There's no email
delivery yet (docs/ARCHITECTURE.md § Known limits): notices show on the billing page and in
the shell's banner.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from django.db import IntegrityError, transaction
from django.utils import timezone

from ..models import BillingNotice

if TYPE_CHECKING:
    from common.auth import TenantClaims

log = logging.getLogger(__name__)
SHOWN = 10


def notify(tenant_id: object, kind: str, key: str, params: dict[str, Any] | None = None) -> bool:
    """True when this is the first time; a repeat of the same key is dropped."""
    try:
        with transaction.atomic():
            BillingNotice.objects.create(tenant_id=tenant_id, kind=kind, key=key, params=params or {})
    except IntegrityError:
        return False
    log.info("billing notice %s for %s", key, tenant_id)
    return True


def notice_dict(n: BillingNotice) -> dict[str, Any]:
    return {
        "id": n.id,
        "kind": n.kind,
        "params": n.params,
        "createdAt": n.created_at.isoformat(),
        "read": n.read_at is not None,
    }


def recent(tenant_id: object) -> list[dict[str, Any]]:
    return [notice_dict(n) for n in BillingNotice.objects.filter(tenant_id=tenant_id)[:SHOWN]]


def mark_read(claims: TenantClaims, notice_id: int) -> None:
    claims.demand_any(("billing.view", "billing.manage"))
    BillingNotice.objects.filter(tenant_id=claims.tenant_id, id=notice_id, read_at__isnull=True).update(
        read_at=timezone.now()
    )
