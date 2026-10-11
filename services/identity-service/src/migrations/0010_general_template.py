"""One template for every business: "general" replaces fitness, rentals & tours and field service.

Tenantly is generic, so a new business no longer picks a vertical. The single template
offers every fulfilment preset (appointment, class, rental, visit, plan) and plain words
("Customer", "Booking", "Team member"); the UI only shows a preset's parts once the
business actually sells something of that kind. Documents and accounts are available
but off until used: the waiver starts "Not needed" and turns on from Policies.

Businesses created from the old templates keep theirs (their words and data stay as
they were); old templates nobody uses are removed. Frozen here on purpose: later edits
to templates are data, not code.
"""

from django.db import migrations

STAFF = {"type": "staff", "quantity": 1, "pick": True}

GENERAL = {
    "id": "general",
    "version": 1,
    "label": "Business",
    "description": "Any business that sells time, capacity or access.",
    "hue": 250,
    "presets": [
        {
            "key": "appointment",
            "label": "Appointment",
            "plural": "Appointments",
            "intro": "One customer at a time with a team member: a haircut, a consultation, a lesson.",
            "capacity": 1,
            "time": "slot",
            "units": ["session"],
            "place": "on_site",
            "requires": [STAFF],
        },
        {
            "key": "class",
            "label": "Class or group",
            "plural": "Classes & groups",
            "intro": "Several customers share one session, up to a limit: a class, a tour, a workshop.",
            "capacity": 12,
            "time": "slot",
            "units": ["session"],
            "place": "on_site",
            "requires": [STAFF],
        },
        {
            "key": "rental",
            "label": "Rental",
            "plural": "Rentals",
            "intro": "A customer takes a room or an item for a while: by the hour, day, night or month.",
            "capacity": 1,
            "time": "window",
            "units": ["hour", "day", "night", "month"],
            "place": "on_site",
            "requires": [{"type": "asset", "quantity": 1, "pick": False, "named": True}],
        },
        {
            "key": "visit",
            "label": "Visit",
            "plural": "Visits",
            "intro": "A team member goes to the customer's address: repairs, cleaning, care.",
            "capacity": 1,
            "time": "slot",
            "units": ["session"],
            "place": "at_customer",
            "requires": [STAFF],
        },
        {
            "key": "plan",
            "label": "Plan or membership",
            "plural": "Plans & memberships",
            "intro": "Recurring access or a pack of credits; not booked on the calendar.",
            "capacity": None,
            "time": "none",
            "units": ["month", "pack"],
            "place": "on_site",
            "requires": [],
        },
    ],
    "resource_types": [
        {
            "key": "staff",
            "label": "Team member",
            "plural": "Team",
            "people": True,
            "roleLabel": "Specialty",
            "attributes": [],
        },
        {
            "key": "asset",
            "label": "Room or item",
            "plural": "Rooms & items",
            "people": False,
            "roleLabel": "Type",
            "attributes": [],
        },
    ],
    "terms": {
        "customer": "Customer",
        "customers": "Customers",
        "booking": "Booking",
        "bookings": "Bookings",
        "staff": "Team member",
        "staffPlural": "Team",
        "asset": "Room or item",
        "assets": "Rooms & items",
        "location": "Location",
        "locations": "Locations",
    },
    "status": {
        "requested": "Requested",
        "confirmed": "Confirmed",
        "checked_in": "Checked in",
        "completed": "Completed",
        "no_show": "No-show",
        "cancelled": "Cancelled",
    },
    "transitions": {
        "requested": ["confirmed", "cancelled"],
        "confirmed": ["checked_in", "no_show", "cancelled"],
        "checked_in": ["completed"],
        "completed": [],
        "no_show": [],
        "cancelled": [],
    },
    "fields": {},
    "account_types": [
        {"key": "business", "label": "Company", "plural": "Companies", "fields": []},
        {"key": "household", "label": "Household", "plural": "Households", "fields": []},
    ],
    "subject_types": [],
    "documents": [{"key": "waiver", "label": "Waiver", "appliesTo": "customer", "validDays": None}],
    "open": 480,
    "close": 1200,
    "policy_defaults": {"docs.require.waiver": "Not needed"},
}

LEGACY = ["fitness", "rentals", "field"]


def forward(apps, schema_editor):
    Template = apps.get_model("identity", "Template")
    Tenant = apps.get_model("identity", "Tenant")
    # Levels and roles as every template has them since 0009.
    area = Template.objects.exclude(levels=[]).values_list("levels", flat=True).first()
    roles = Template.objects.exclude(roles=[]).values_list("roles", flat=True).first()
    Template.objects.update_or_create(
        id=GENERAL["id"],
        defaults={
            **{k: v for k, v in GENERAL.items() if k != "id"},
            "levels": area or [{"key": "area", "label": "Area", "plural": "Areas"}],
            "roles": roles or [],
        },
    )
    used = set(Tenant.objects.values_list("template_id", flat=True))
    Template.objects.filter(id__in=[t for t in LEGACY if t not in used]).delete()


def backward(apps, schema_editor):
    Tenant = apps.get_model("identity", "Tenant")
    if not Tenant.objects.filter(template_id=GENERAL["id"]).exists():
        apps.get_model("identity", "Template").objects.filter(id=GENERAL["id"]).delete()


class Migration(migrations.Migration):
    dependencies = [
        ("identity", "0009_seed_levels_and_roles"),
    ]

    operations = [migrations.RunPython(forward, backward)]
