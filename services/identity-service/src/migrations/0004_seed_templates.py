"""Seed the three original templates (formerly services/common/templates.py)."""

from django.db import migrations

TEMPLATES = [
    {
        "id": "fitness",
        "version": 1,
        "label": "Fitness",
        "description": "Gyms, studios and clubs: classes, personal training and memberships.",
        "hue": 292,
        "kinds": ["class", "appointment", "plan"],
        "terms": {
            "customer": "Member",
            "customers": "Members",
            "booking": "Booking",
            "bookings": "Bookings",
            "staff": "Coach",
            "staffPlural": "Coaches",
            "asset": "Room",
            "assets": "Rooms",
            "location": "Club",
            "locations": "Clubs",
        },
        "status": {
            "requested": "Waitlisted",
            "confirmed": "Booked",
            "checked_in": "Checked in",
            "completed": "Attended",
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
        "customer_fields": [
            {"key": "goal", "label": "Goal"},
            {"key": "injuries", "label": "Injuries"},
            {"key": "emergency", "label": "Emergency contact"},
        ],
        "waiver": True,
        "open": 360,
        "close": 1260,
        "policy_defaults": {"docs.waiver": True},
    },
    {
        "id": "rentals",
        "version": 1,
        "label": "Rentals & tours",
        "description": "Kayaks, bikes, boards, courts or rooms by the hour, plus guided tours.",
        "hue": 205,
        "kinds": ["rental", "class"],
        "terms": {
            "customer": "Renter",
            "customers": "Renters",
            "booking": "Reservation",
            "bookings": "Reservations",
            "staff": "Guide",
            "staffPlural": "Guides",
            "asset": "Unit",
            "assets": "Fleet",
            "location": "Dock",
            "locations": "Docks",
        },
        "status": {
            "requested": "Requested",
            "confirmed": "Reserved",
            "checked_in": "Out",
            "completed": "Returned",
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
        "customer_fields": [
            {"key": "id", "label": "ID checked"},
            {"key": "experience", "label": "Experience"},
            {"key": "emergency", "label": "Emergency contact"},
        ],
        "waiver": True,
        "open": 480,
        "close": 1140,
        "policy_defaults": {"docs.waiver": True},
    },
    {
        "id": "field",
        "version": 1,
        "label": "Field service",
        "description": "Crews that go to the customer: cleaning, maintenance, repairs, care plans.",
        "hue": 155,
        "kinds": ["visit", "plan"],
        "terms": {
            "customer": "Account",
            "customers": "Accounts",
            "booking": "Visit",
            "bookings": "Visits",
            "staff": "Technician",
            "staffPlural": "Technicians",
            "asset": "Van",
            "assets": "Vans",
            "location": "Route",
            "locations": "Routes",
        },
        "status": {
            "requested": "Requested",
            "confirmed": "Scheduled",
            "checked_in": "On site",
            "completed": "Completed",
            "no_show": "No access",
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
        "customer_fields": [
            {"key": "address", "label": "Address"},
            {"key": "system", "label": "System"},
            {"key": "access", "label": "Access notes"},
        ],
        "waiver": False,
        "open": 480,
        "close": 1080,
        "policy_defaults": {"docs.waiver": False},
    },
]


def seed(apps, schema_editor):
    Template = apps.get_model("identity", "Template")
    for row in TEMPLATES:
        Template.objects.update_or_create(id=row["id"], defaults=row)


def unseed(apps, schema_editor):
    apps.get_model("identity", "Template").objects.filter(id__in=[t["id"] for t in TEMPLATES]).delete()


class Migration(migrations.Migration):
    dependencies = [
        ("identity", "0003_template"),
    ]

    operations = [migrations.RunPython(seed, unseed)]
