"""End a Tenantly admin's access window now. Their tokens stop working; the account is kept.

manage.py block_admin you@tenantly.dev
"""

from __future__ import annotations

from typing import Any

from django.core.management.base import BaseCommand, CommandError

from common.errors import ApiError

from ...services import admins
from ._admin_cli import operator


class Command(BaseCommand):
    help = "Block a Tenantly admin now (never deletes it)."

    def add_arguments(self, parser: Any) -> None:
        parser.add_argument("email")

    def handle(self, *args: Any, **options: Any) -> None:  # noqa: ARG002
        try:
            admin = admins.block(options["email"], operator())
        except ApiError as e:
            raise CommandError(e.detail) from e
        self.stdout.write(f"{admin.email}: blocked")
