"""Gaps 3-4: offering kinds become fulfilment presets; resource types become template data.

Every stored template's `kinds` list turns into `presets` (the rules each kind used to
hard-code), and its `staff` / `asset` words into two resource types. The three seeded
templates also get one optional typed attribute on their asset type. Frozen here on
purpose: later edits to templates are data, not code.
"""

from django.db import migrations, models

STAFF = {"type": "staff", "quantity": 1, "pick": True}

PRESETS = {
    "appointment": {
        "label": "Appointment",
        "plural": "Appointments",
        "intro": "One customer, one team member, a fixed length.",
        "capacity": 1,
        "time": "slot",
        "units": ["session"],
        "place": "on_site",
        "requires": [STAFF],
    },
    "class": {
        "label": "Class",
        "plural": "Classes",
        "intro": "Many customers share one session, up to a capacity.",
        "capacity": 12,
        "time": "slot",
        "units": ["session"],
        "place": "on_site",
        "requires": [STAFF],
    },
    "rental": {
        "label": "Rental",
        "plural": "Rentals",
        "intro": "A customer takes a unit for a window of time.",
        "capacity": 1,
        "time": "window",
        "units": ["hour", "day", "night", "month"],
        "place": "on_site",
        "requires": [{"type": "asset", "quantity": 1, "pick": False, "named": True}],
    },
    "visit": {
        "label": "Visit",
        "plural": "Visits",
        "intro": "A team member goes to the customer’s address.",
        "capacity": 1,
        "time": "slot",
        "units": ["session"],
        "place": "at_customer",
        "requires": [STAFF],
    },
    "plan": {
        "label": "Plan",
        "plural": "Plans",
        "intro": "Recurring access or a bundle of credits — not a time slot.",
        "capacity": None,
        "time": "none",
        "units": ["month", "pack"],
        "place": "on_site",
        "requires": [],
    },
}

ASSET_ATTRIBUTES = {
    "fitness": [{"key": "capacity", "label": "Capacity", "type": "number"}],
    "rentals": [{"key": "seats", "label": "Seats", "type": "number"}],
    "field": [{"key": "plate", "label": "Plate", "type": "text"}],
}


def _resource_types(template_id, terms):
    return [
        {
            "key": "staff",
            "label": terms.get("staff", "Team member"),
            "plural": terms.get("staffPlural", "Team"),
            "people": True,
            "roleLabel": "Specialty",
            "attributes": [],
        },
        {
            "key": "asset",
            "label": terms.get("asset", "Asset"),
            "plural": terms.get("assets", "Assets"),
            "people": False,
            "roleLabel": "Type",
            "attributes": ASSET_ATTRIBUTES.get(template_id, []),
        },
    ]


def forward(apps, schema_editor):
    Template = apps.get_model("identity", "Template")
    for t in Template.objects.all():
        t.presets = [{"key": k, **PRESETS[k]} for k in t.kinds if k in PRESETS]
        t.resource_types = _resource_types(t.id, t.terms)
        t.version += 1
        t.save(update_fields=["presets", "resource_types", "version"])


def backward(apps, schema_editor):
    Template = apps.get_model("identity", "Template")
    for t in Template.objects.all():
        t.kinds = [p["key"] for p in t.presets if p.get("key") in PRESETS]
        t.save(update_fields=["kinds"])


class Migration(migrations.Migration):
    dependencies = [
        ("identity", "0005_location_clock"),
    ]

    operations = [
        migrations.AddField(model_name="template", name="presets", field=models.JSONField(default=list)),
        migrations.AddField(model_name="template", name="resource_types", field=models.JSONField(default=list)),
        migrations.RunPython(forward, backward),
        migrations.RemoveField(model_name="template", name="kinds"),
    ]
