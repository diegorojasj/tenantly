"""Open a Tenantly admin's access window for ADMIN_WINDOW_MINUTES (default 10) from now.

manage.py activate_admin you@tenantly.dev
manage.py activate_admin you@tenantly.dev --password "…"   # at least 12 characters, not the current one

The only way back in after a window closes: there is no reactivation from the web. Every
activation replaces the password: without --password a strong one is generated and printed once.
"""

from __future__ import annotations

from typing import Any

from django.core.management.base import BaseCommand, CommandError

from common.errors import ApiError

from ...services import admins
from ._admin_cli import operator


class Command(BaseCommand):
    help = "Open a new time-boxed access window for a Tenantly admin, with a new password."

    def add_arguments(self, parser: Any) -> None:
        parser.add_argument("email")
        parser.add_argument("--password", help="The new password, at least 12 characters; generated if left out.")

    def handle(self, *args: Any, **options: Any) -> None:  # noqa: ARG002
        try:
            admin, generated = admins.activate(options["email"], operator(), options["password"])
        except ApiError as e:
            raise CommandError(e.detail) from e
        until = admin.active_until.isoformat() if admin.active_until else "?"
        self.stdout.write(f"{admin.email}: access window open until {until}")
        if generated:
            self.stdout.write(f"new password (shown once): {generated}")
        else:
            self.stdout.write("password replaced with the one given")
