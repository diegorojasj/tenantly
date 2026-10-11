"""Gap 8: named tree levels and per-tenant roles, seeded so nothing changes for existing businesses.

Every stored template gains one group level, "Area" (what the tree always had between
the business and its locations), and the six platform roles as its default roles.
Every existing group node is put on that level, and every business gets its own copy
of its template's roles, so each membership keeps exactly the permissions it had.
Frozen here on purpose: later edits to templates and roles are data, not code.
"""

from django.db import migrations

AREA = {"key": "area", "label": "Area", "plural": "Areas"}

EVERYTHING = [
    "bookings.manage",
    "payments.collect",
    "tenant.manage",
    "members.invite",
    "roles.assign",
    "config.write",
    "pricing.write",
    "billing.view",
    "billing.manage",
    "audit.view",
    "integrations.manage",
    "analytics.view",
]

ROLES = [
    {
        "id": "owner",
        "label": "Owner",
        "summary": "Full control of the business, including billing.",
        "permissions": EVERYTHING,
    },
    {
        "id": "admin",
        "label": "Admin",
        "summary": "Runs day-to-day operations; cannot change the Tenantly plan.",
        "permissions": [p for p in EVERYTHING if p not in {"tenant.manage", "billing.manage"}],
    },
    {
        "id": "regional_manager",
        "label": "Area manager",
        "summary": "Runs bookings, catalog and policies for one area.",
        "permissions": [
            "bookings.manage",
            "payments.collect",
            "members.invite",
            "config.write",
            "pricing.write",
            "audit.view",
            "analytics.view",
        ],
    },
    {
        "id": "location_manager",
        "label": "Front desk lead",
        "summary": "Runs the desk of a single site: bookings, check-ins, payments.",
        "permissions": ["bookings.manage", "payments.collect", "config.write", "analytics.view"],
    },
    {
        "id": "analyst",
        "label": "Analyst",
        "summary": "Read-only access to bookings, numbers and settings.",
        "permissions": ["analytics.view", "billing.view"],
    },
    {
        "id": "auditor",
        "label": "Auditor",
        "summary": "Read-only access to the audit trail and billing.",
        "permissions": ["audit.view", "billing.view"],
    },
]


def forward(apps, schema_editor):
    Template = apps.get_model("identity", "Template")
    Tenant = apps.get_model("identity", "Tenant")
    Node = apps.get_model("identity", "Node")
    Role = apps.get_model("identity", "Role")
    for t in Template.objects.all():
        t.levels = t.levels or [dict(AREA)]
        t.roles = t.roles or [dict(r, permissions=list(r["permissions"])) for r in ROLES]
        t.version += 1
        t.save()
    templates = {t.id: t for t in Template.objects.all()}
    for tenant in Tenant.objects.all():
        template = templates.get(tenant.template_id)
        levels = (template.levels if template else None) or [AREA]
        Node.objects.filter(tenant=tenant, kind="region", level="").update(level=levels[0]["key"])
        for r in (template.roles if template else None) or ROLES:
            Role.objects.get_or_create(
                tenant=tenant,
                key=r["id"],
                defaults={
                    "label": r["label"],
                    "summary": r.get("summary", ""),
                    "permissions": list(r["permissions"]),
                    "builtin": True,
                },
            )


def backward(apps, schema_editor):
    Template = apps.get_model("identity", "Template")
    Node = apps.get_model("identity", "Node")
    Role = apps.get_model("identity", "Role")
    Role.objects.all().delete()
    Node.objects.update(level="")
    for t in Template.objects.all():
        t.levels = []
        t.roles = []
        t.version = max(1, t.version - 1)
        t.save()


class Migration(migrations.Migration):
    dependencies = [
        ("identity", "0008_tree_levels_roles_money_branding"),
    ]

    operations = [migrations.RunPython(forward, backward)]
