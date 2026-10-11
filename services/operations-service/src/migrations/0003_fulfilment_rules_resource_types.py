"""Gaps 3-4: offerings carry fulfilment rules; resources get typed attributes and nesting.

Each offering's kind, `needs_staff` and `asset_type` become explicit rules that book
exactly as before:

- capacity: classes keep theirs; every other bookable offering books one customer (1);
- time: plans none, hourly rentals window, day / night / month rentals span, the rest slot;
- place: visits at the customer, the rest on site;
- requires: one picked `staff` when it needed staff, then one auto-assigned `asset` of
  its asset type.

Resource types stay `staff` / `asset`: the keys the migrated templates define.
"""

from django.db import migrations, models
import django.db.models.deletion

SPAN_UNITS = {"day", "night", "month"}


def forward(apps, schema_editor):
    Offering = apps.get_model("operations", "Offering")
    for o in Offering.objects.all():
        if o.kind == "plan":
            o.time, o.capacity, o.requires = "none", None, []
        else:
            o.time = "window" if o.unit == "hour" else "span" if o.unit in SPAN_UNITS else "slot"
            o.capacity = o.capacity or 1
            requires = []
            if o.needs_staff:
                requires.append({"type": "staff", "quantity": 1, "pick": True, "role": None})
            if o.asset_type:
                requires.append({"type": "asset", "quantity": 1, "pick": False, "role": o.asset_type})
            o.requires = requires
        o.place = "at_customer" if o.kind == "visit" else "on_site"
        o.save(update_fields=["time", "capacity", "requires", "place"])


def backward(apps, schema_editor):
    Offering = apps.get_model("operations", "Offering")
    for o in Offering.objects.all():
        o.needs_staff = any(r.get("type") == "staff" for r in o.requires)
        o.asset_type = next((r.get("role") for r in o.requires if r.get("type") == "asset"), None)
        if o.kind != "class":
            o.capacity = None
        o.save(update_fields=["needs_staff", "asset_type", "capacity"])


class Migration(migrations.Migration):
    dependencies = [
        ("operations", "0002_money_outbox"),
    ]

    operations = [
        migrations.AlterField(model_name="offering", name="kind", field=models.CharField(max_length=20)),
        migrations.AddField(
            model_name="offering",
            name="time",
            field=models.CharField(
                choices=[("slot", "Slot"), ("window", "Window"), ("span", "Span"), ("none", "None")],
                default="slot",
                max_length=6,
            ),
        ),
        migrations.AddField(
            model_name="offering",
            name="place",
            field=models.CharField(
                choices=[("on_site", "On Site"), ("at_customer", "At Customer")], default="on_site", max_length=12
            ),
        ),
        migrations.AddField(model_name="offering", name="requires", field=models.JSONField(default=list)),
        migrations.RunPython(forward, backward),
        migrations.RemoveField(model_name="offering", name="needs_staff"),
        migrations.RemoveField(model_name="offering", name="asset_type"),
        migrations.AlterField(model_name="resource", name="type", field=models.CharField(max_length=30)),
        migrations.AlterField(model_name="resource", name="role", field=models.CharField(max_length=60)),
        migrations.AddField(
            model_name="resource", name="attributes", field=models.JSONField(blank=True, default=dict)
        ),
        migrations.AddField(
            model_name="resource",
            name="parent",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name="children",
                to="operations.resource",
            ),
        ),
    ]
