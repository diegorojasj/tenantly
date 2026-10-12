"""The Tenantly plan catalog (docs/BILLING.md §4).

v1 is what businesses signed up on before usage billing: the same prices and customer
allowances, with the old "billed on the next tier" cliff replaced by overage capped at that
next tier, so nobody already subscribed pays more than before. It is `legacy`: honoured for
the tenants on it, no longer offered. v2 is the public price list.
"""

from datetime import UTC, datetime
from decimal import Decimal

from django.db import migrations

LAUNCH = datetime(2026, 1, 1, tzinfo=UTC)
USAGE_BILLING = datetime(2026, 10, 12, tzinfo=UTC)

CATALOG = [
    # code, version, name, base, included customers, overage per customer, cap, rank, status, since
    ("starter", 1, "Starter", "29.00", 50, "0.50", "49.00", 1, "legacy", LAUNCH),
    ("growth", 1, "Growth", "49.00", 100, "0.40", "89.00", 2, "legacy", LAUNCH),
    # The old Enterprise never billed past its price: still no overage on v1.
    ("enterprise", 1, "Enterprise", "89.00", 200, None, None, 3, "legacy", LAUNCH),
    ("starter", 2, "Starter", "29.00", 75, "0.40", "59.00", 1, "active", USAGE_BILLING),
    ("growth", 2, "Growth", "59.00", 200, "0.30", "129.00", 2, "active", USAGE_BILLING),
    ("enterprise", 2, "Enterprise", "129.00", 500, "0.25", None, 3, "active", USAGE_BILLING),
]


def forward(apps, schema_editor):
    PlanVersion = apps.get_model("billing", "PlanVersion")
    for code, version, name, base, included, overage, cap, rank, status, since in CATALOG:
        PlanVersion.objects.update_or_create(
            code=code,
            version=version,
            defaults={
                "name": name,
                "currency": "USD",
                "base_price": Decimal(base),
                "included": {"active_customers": included},
                "overage_price": {"active_customers": overage} if overage else {},
                "overage_cap": Decimal(cap) if cap else None,
                "rank": rank,
                "status": status,
                "effective_from": since,
            },
        )


def backward(apps, schema_editor):
    PlanVersion = apps.get_model("billing", "PlanVersion")
    PlanVersion.objects.filter(tenant_id__isnull=True, code__in=["starter", "growth", "enterprise"]).delete()


class Migration(migrations.Migration):
    dependencies = [
        ("billing", "0004_usage_billing"),
    ]

    operations = [migrations.RunPython(forward, backward)]
