"""Move a business to a Tenantly plan, e.g. the Custom plan agreed with its owner.

manage.py set_plan ironworks Growth
manage.py set_plan ironworks Custom --price 250 --customers 1000
"""

from __future__ import annotations

from typing import Any

from django.core.management.base import BaseCommand, CommandError
from pydantic import ValidationError

from common.errors import InvalidError

from ...models import Tenant
from ...schemas import PlanIn
from ...services import plan


class Command(BaseCommand):
    help = "Set a business's Tenantly plan (Custom takes its negotiated price and limits)."

    def add_arguments(self, parser: Any) -> None:
        parser.add_argument("slug")
        parser.add_argument("plan", choices=["Starter", "Growth", "Enterprise", "Custom"])
        parser.add_argument("--price", help="Custom only: USD a month.")
        parser.add_argument("--customers", type=int, help="Custom only: customers a month (none if left out).")
        parser.add_argument("--payments", type=int, help="Custom only: payments a month (none if left out).")

    def handle(self, *args: Any, **options: Any) -> None:  # noqa: ARG002
        tenant = Tenant.objects.filter(slug=options["slug"]).first()
        if not tenant:
            msg = f"No business with slug {options['slug']!r}"
            raise CommandError(msg)
        terms = None
        if options["plan"] == "Custom":
            terms = {
                "price": options["price"],
                "customerLimit": options["customers"],
                "paymentLimit": options["payments"],
            }
        try:
            held = plan.assign(str(tenant.id), PlanIn.model_validate({"plan": options["plan"], "terms": terms}))
        except (ValidationError, InvalidError) as e:
            raise CommandError(str(e)) from e
        self.stdout.write(f"{tenant.slug}: {held['plan']} {held['terms'] or ''}".rstrip())
