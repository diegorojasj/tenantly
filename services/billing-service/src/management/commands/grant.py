"""An exception Tenantly authorises for one business: bounded in time, with a reason, audited.

manage.py grant <tenant-id> extra_allowance --metric active_customers --value 50 --days 31 --reason "launch week"
manage.py grant <tenant-id> dispute --days 14 --reason "invoice TNT-000123 under review"
"""

from __future__ import annotations

from decimal import Decimal, InvalidOperation
from typing import Any

from django.core.management.base import BaseCommand, CommandError

from common.errors import ApiError

from ...models import EntitlementGrant
from ...services import grants


class Command(BaseCommand):
    help = "Grant a business extra allowance, a discount, waived overage, more grace, or pause collections."

    def add_arguments(self, parser: Any) -> None:
        parser.add_argument("tenant_id")
        parser.add_argument("kind", choices=[k.value for k in EntitlementGrant.Kind])
        parser.add_argument("--metric", default="", help="extra_allowance: which metric (active_customers).")
        parser.add_argument("--value", default="0", help="Units, percent or days, by kind.")
        parser.add_argument("--days", type=int, default=31, help="How long the grant lasts, from now.")
        parser.add_argument("--reason", required=True)
        parser.add_argument("--by", default="Tenantly staff", help="Who approved it.")

    def handle(self, *args: Any, **options: Any) -> None:  # noqa: ARG002
        try:
            value = Decimal(options["value"])
        except InvalidOperation as e:
            msg = f"Not a number: {options['value']!r}"
            raise CommandError(msg) from e
        try:
            grant = grants.grant(
                options["tenant_id"],
                options["kind"],
                metric=options["metric"],
                value=value,
                days=options["days"],
                reason=options["reason"],
                actor=("tenantly", options["by"]),
            )
        except ApiError as e:
            raise CommandError(e.detail) from e
        self.stdout.write(f"granted {grant}")
