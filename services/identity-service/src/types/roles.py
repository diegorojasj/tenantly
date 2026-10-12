"""Permissions, and the platform's default roles (docs/USAGE.md §1).

Permissions are code: each one guards something a service checks. Roles are data
(docs/PLATFORM.md gap 8): a template lists the roles a new business starts with
(seeded from `ROLES` below), and each business keeps its own editable copy as
`Role` rows. `owner` is the one fixed role: it always holds every permission.
"""

from __future__ import annotations

from typing import Any

from django.utils.translation import gettext_lazy

# Lazy translations: `str()` them where they are served, in the request's language.
PERMISSION_LABELS: dict[str, Any] = {
    "bookings.manage": gettext_lazy("Book, check in & cancel"),
    "payments.collect": gettext_lazy("Collect & refund payments"),
    "tenant.manage": gettext_lazy("Manage business"),
    "members.invite": gettext_lazy("Invite team"),
    "roles.assign": gettext_lazy("Assign roles"),
    "config.write": gettext_lazy("Edit policies & resources"),
    "pricing.write": gettext_lazy("Edit catalog & prices"),
    "billing.view": gettext_lazy("View Tenantly plan"),
    "billing.manage": gettext_lazy("Manage Tenantly plan"),
    "audit.view": gettext_lazy("View audit trail"),
    "analytics.view": gettext_lazy("View insights"),
}

ROLES: list[dict[str, Any]] = [
    {
        "id": "owner",
        "label": gettext_lazy("Owner"),
        "summary": gettext_lazy("Full control of the business, including billing."),
        "permissions": list(PERMISSION_LABELS),
    },
    {
        "id": "admin",
        "label": gettext_lazy("Admin"),
        "summary": gettext_lazy("Runs day-to-day operations; cannot change the Tenantly plan."),
        "permissions": [
            "bookings.manage",
            "payments.collect",
            "members.invite",
            "roles.assign",
            "config.write",
            "pricing.write",
            "billing.view",
            "audit.view",
            "analytics.view",
        ],
    },
    {
        "id": "regional_manager",
        "label": gettext_lazy("Area manager"),
        "summary": gettext_lazy("Runs bookings, catalog and policies for one area."),
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
        "label": gettext_lazy("Front desk lead"),
        "summary": gettext_lazy("Runs the desk of a single site: bookings, check-ins, payments."),
        "permissions": ["bookings.manage", "payments.collect", "config.write", "analytics.view"],
    },
    {
        "id": "analyst",
        "label": gettext_lazy("Analyst"),
        "summary": gettext_lazy("Read-only access to bookings, numbers and settings."),
        "permissions": ["analytics.view", "billing.view"],
    },
    {
        "id": "auditor",
        "label": gettext_lazy("Auditor"),
        "summary": gettext_lazy("Read-only access to the audit trail and billing."),
        "permissions": ["audit.view", "billing.view"],
    },
]

OWNER = "owner"
# Held by the owner alone, never by another role: the business's Tenantly subscription is the
# owner's, and the team works under it.
OWNER_ONLY = frozenset({"billing.manage"})
