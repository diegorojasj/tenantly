"""Gaps 5-6: typed custom fields, account and subject types, documents instead of the waiver flag.

Every stored template's `customer_fields` (`{key, label}`) become typed text fields under
`fields["customer"]`, and its `waiver` flag becomes a "waiver" document type. The policy
default `docs.waiver` (a bool) becomes `docs.require.waiver` (Not needed / Remind / Required
to book): `True` maps to "Remind", which is what the flag did (flag customers, warn on
arrival), so nothing starts blocking bookings. The three seeded templates also gain PII
markings, account types, and (field service) a property subject type with an optional
certificate. Frozen here on purpose: later edits to templates are data, not code.
"""

from django.db import migrations, models

OFF, REMIND = "Not needed", "Remind"
WAIVER = {"key": "waiver", "label": "Waiver", "appliesTo": "customer", "validDays": None}

PII = {
    "fitness": {"injuries", "emergency"},
    "rentals": {"id", "emergency"},
    "field": {"address", "access"},
}

ACCOUNT_TYPES = {
    "fitness": [{"key": "household", "label": "Family", "plural": "Families", "fields": []}],
    "rentals": [{"key": "business", "label": "Group", "plural": "Groups", "fields": []}],
    "field": [
        {
            "key": "business",
            "label": "Company",
            "plural": "Companies",
            "fields": [{"key": "taxId", "label": "Tax ID", "type": "text"}],
        },
        {"key": "household", "label": "Household", "plural": "Households", "fields": []},
    ],
}

SUBJECT_TYPES = {
    "field": [
        {
            "key": "property",
            "label": "Property",
            "plural": "Properties",
            "fields": [
                {"key": "address", "label": "Address", "type": "text", "required": True, "pii": True},
                {"key": "system", "label": "System", "type": "text"},
                {"key": "serviced", "label": "Last serviced", "type": "date"},
            ],
        }
    ],
}

EXTRA_DOCUMENTS = {
    "field": [
        {
            "key": "gas_cert",
            "label": "Gas safety certificate",
            "appliesTo": "subject",
            "subjectType": "property",
            "validDays": 365,
        }
    ],
}


def forward(apps, schema_editor):
    Template = apps.get_model("identity", "Template")
    for t in Template.objects.all():
        pii = PII.get(t.id, set())
        t.fields = {
            "customer": [
                {"key": f["key"], "label": f["label"], "type": "text", **({"pii": True} if f["key"] in pii else {})}
                for f in t.customer_fields
            ]
        }
        t.account_types = ACCOUNT_TYPES.get(t.id, [])
        t.subject_types = SUBJECT_TYPES.get(t.id, [])
        t.documents = ([dict(WAIVER)] if t.waiver else []) + EXTRA_DOCUMENTS.get(t.id, [])
        defaults = dict(t.policy_defaults)
        if "docs.waiver" in defaults:
            if defaults.pop("docs.waiver") is True:
                defaults["docs.require.waiver"] = REMIND
        t.policy_defaults = defaults
        t.version += 1
        t.save()


def backward(apps, schema_editor):
    Template = apps.get_model("identity", "Template")
    for t in Template.objects.all():
        t.customer_fields = [{"key": f["key"], "label": f["label"]} for f in (t.fields or {}).get("customer", [])]
        t.waiver = any(d.get("key") == "waiver" for d in t.documents)
        defaults = dict(t.policy_defaults)
        defaults["docs.waiver"] = defaults.pop("docs.require.waiver", OFF) != OFF
        t.policy_defaults = defaults
        t.version = max(1, t.version - 1)
        t.save()


class Migration(migrations.Migration):
    dependencies = [
        ("identity", "0006_template_presets_resource_types"),
    ]

    operations = [
        migrations.AddField(model_name="template", name="fields", field=models.JSONField(default=dict)),
        migrations.AddField(model_name="template", name="account_types", field=models.JSONField(default=list)),
        migrations.AddField(model_name="template", name="subject_types", field=models.JSONField(default=list)),
        migrations.AddField(model_name="template", name="documents", field=models.JSONField(default=list)),
        migrations.RunPython(forward, backward),
        migrations.RemoveField(model_name="template", name="customer_fields"),
        migrations.RemoveField(model_name="template", name="waiver"),
    ]
