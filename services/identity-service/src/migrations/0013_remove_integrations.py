"""Integrations are not planned yet: drop the per-tenant switches and the permission that guarded them.

Every stored template role and business role loses `integrations.manage`; the rest of
their permissions are untouched. Past `integration` audit events stay in the trail.
"""

from django.db import migrations

PERMISSION = "integrations.manage"


def forward(apps, schema_editor):
    Template = apps.get_model("identity", "Template")
    Role = apps.get_model("identity", "Role")
    for t in Template.objects.all():
        if any(PERMISSION in r.get("permissions", []) for r in t.roles):
            t.roles = [dict(r, permissions=[p for p in r["permissions"] if p != PERMISSION]) for r in t.roles]
            t.save(update_fields=["roles"])
    for role in Role.objects.all():
        if PERMISSION in role.permissions:
            role.permissions = [p for p in role.permissions if p != PERMISSION]
            role.save(update_fields=["permissions"])


class Migration(migrations.Migration):
    dependencies = [("identity", "0012_seed_spanish")]

    operations = [
        migrations.RunPython(forward, migrations.RunPython.noop),
        migrations.DeleteModel(name="IntegrationState"),
    ]
