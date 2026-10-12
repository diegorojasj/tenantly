"""Move a business to a Tenantly plan now, e.g. the Custom plan agreed with its owner.

Billing applies it (docs/BILLING.md): an upgrade prorates from today, and the change lands
in the business's history and audit trail.

manage.py set_plan ironworks growth
manage.py set_plan ironworks custom --price 250 --customers 1000 --overage 0.20 --reason "3-year deal"
"""

from __future__ import annotations

from typing import Any

from django.core.management.base import BaseCommand, CommandError
from pydantic import ValidationError

from common.errors import ApiError

from ...models import Tenant
from ...schemas import PlanIn
from ...services import plan

NAMES = {"starter": "Starter", "growth": "Growth", "enterprise": "Enterprise", "custom": "Custom"}


class Command(BaseCommand):
    help = "Set a business's Tenantly plan (custom takes its negotiated price and limits)."

    def add_arguments(self, parser: Any) -> None:
        parser.add_argument("slug")
        parser.add_argument("plan", type=str.lower, choices=list(NAMES))
        parser.add_argument("--price", help="custom only: USD a month.")
        parser.add_argument("--customers", type=int, help="custom only: active customers included (none: no limit).")
        parser.add_argument("--overage", help="custom only: USD per active customer past --customers.")
        parser.add_argument("--reason", default="", help="Why, for the subscription's history.")

    def handle(self, *args: Any, **options: Any) -> None:  # noqa: ARG002
        tenant = Tenant.objects.filter(slug=options["slug"]).first()
        if not tenant:
            msg = f"No business with slug {options['slug']!r}"
            raise CommandError(msg)
        terms = None
        if options["plan"] == "custom":
            terms = {
                "price": options["price"],
                "customerLimit": options["customers"],
                "overagePrice": options["overage"],
            }
        try:
            body = PlanIn.model_validate({"plan": NAMES[options["plan"]], "terms": terms, "reason": options["reason"]})
            held = plan.assign(str(tenant.id), body)
        except ValidationError as e:
            raise CommandError(str(e)) from e
        except ApiError as e:
            raise CommandError(e.detail) from e
        self.stdout.write(f"{tenant.slug}: {held['plan']} ({held['status']})")
