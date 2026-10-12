"""Open a business for an owner from the server: the admin console's "New owner", for scripts.

There's no public sign-up, so this (or the console) is how an owner's account comes to be.
The owner's account is created when it doesn't exist yet (`--name` and `--password` needed);
an existing owner gets another business. Prints the business as JSON. Set its plan with
`set_plan` (billing starts it on Starter on first use otherwise).

manage.py open_business ana@example.com "Ironworks Gym" --location "Union Square" --name "Ana Solís" --password ...
"""

from __future__ import annotations

import json
from typing import Any

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from common.errors import ApiError

from ...models import AdminAuditEvent, User
from ...services import accounts, admins, tenants
from ._admin_cli import operator


class Command(BaseCommand):
    help = "Create a business owner's account (if needed) and open a business for them."

    def add_arguments(self, parser: Any) -> None:
        parser.add_argument("email")
        parser.add_argument("business")
        parser.add_argument("--location", required=True, help="The business's first location.")
        parser.add_argument("--industry", default="")
        parser.add_argument("--currency", default="USD")
        parser.add_argument("--name", help="New owners only: their name.")
        parser.add_argument("--password", help="New owners only: their first password.")

    @transaction.atomic
    def handle(self, *args: Any, **options: Any) -> None:  # noqa: ARG002
        email = options["email"].strip().lower()
        owner = User.objects.filter(email=email).first()
        try:
            if not owner:
                if not options["name"] or not options["password"]:
                    msg = f"{email} has no account yet: give --name and --password"
                    raise CommandError(msg)
                owner = accounts.create_account(options["name"], email, options["password"])
            elif owner.created_by_id:
                msg = f"{email} is a team account: only owners get businesses"
                raise CommandError(msg)
            tenant = tenants.create_tenant(
                owner,
                name=options["business"],
                industry=options["industry"],
                location_name=options["location"],
                currency=options["currency"],
            )
        except ApiError as e:
            raise CommandError(e.detail) from e
        after = {"email": owner.email, "business": tenant.name, "by": operator()}
        admins.record(
            None, AdminAuditEvent.Kind.ACTION, action="business.created", target=("tenant", str(tenant.id)), after=after
        )
        self.stdout.write(json.dumps({"id": str(tenant.id), "slug": tenant.slug, "name": tenant.name}))
