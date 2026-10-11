"""Usage-based Tenantly plans: Starter, Growth, Enterprise and a negotiated Custom plan.

Plans no longer count seats. The new default is Starter; Scale is gone, so a business on
it moves to Enterprise (its nearest tier). Going back turns Starter into Growth, the old
default, and drops the custom terms.
"""

from django.db import migrations, models


def forward(apps, schema_editor):
    Tenant = apps.get_model("identity", "Tenant")
    Tenant.objects.filter(plan="Scale").update(plan="Enterprise")


def backward(apps, schema_editor):
    Tenant = apps.get_model("identity", "Tenant")
    Tenant.objects.filter(plan__in=("Starter", "Custom")).update(plan="Growth")


class Migration(migrations.Migration):
    dependencies = [
        ("identity", "0013_remove_integrations"),
    ]

    operations = [
        migrations.AlterField(
            model_name="tenant",
            name="plan",
            field=models.CharField(default="Starter", max_length=20),
        ),
        migrations.AddField(
            model_name="tenant",
            name="plan_terms",
            field=models.JSONField(blank=True, default=dict),
        ),
        migrations.RunPython(forward, backward),
    ]
