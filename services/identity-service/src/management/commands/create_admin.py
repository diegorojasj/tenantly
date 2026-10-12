"""Create a Tenantly admin (staff who open the admin console) and open their first access window.

manage.py create_admin you@tenantly.dev --name "You"
manage.py create_admin you@tenantly.dev --name "You" --password "…"   # at least 12 characters
manage.py create_admin you@tenantly.dev --name "You" --dormant        # no window yet

Without --password a strong one is generated and printed once: keep it safe. Admins are not
tenant accounts and are never deleted; `activate_admin` opens a new window, `block_admin` ends it.
"""

from __future__ import annotations

from typing import Any

from django.core.management.base import BaseCommand, CommandError

from common.errors import ApiError

from ...services import admins
from ._admin_cli import operator


class Command(BaseCommand):
    help = "Create a Tenantly admin and open a time-boxed access window (ADMIN_WINDOW_MINUTES)."

    def add_arguments(self, parser: Any) -> None:
        parser.add_argument("email")
        parser.add_argument("--name", required=True)
        parser.add_argument("--password", help="At least 12 characters; generated if left out.")
        parser.add_argument("--dormant", action="store_true", help="Create it without opening a window.")

    def handle(self, *args: Any, **options: Any) -> None:  # noqa: ARG002
        try:
            admin, generated = admins.create(
                options["email"], options["name"], options["password"], operator(), open_window=not options["dormant"]
            )
        except ApiError as e:
            raise CommandError(e.detail) from e
        self.stdout.write(f"{admin.email}: created as a Tenantly admin ({admin.status})")
        if admin.active_until:
            self.stdout.write(f"access window open until {admin.active_until.isoformat()}")
        if generated:
            self.stdout.write(f"password (shown once): {generated}")
