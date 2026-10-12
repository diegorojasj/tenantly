"""Record a Tenantly invoice paid by transfer (or any way other than the saved card).

manage.py mark_paid TNT-000123 --ref "wire 2026-10-30 #8841"
"""

from __future__ import annotations

from typing import Any

from django.core.management.base import BaseCommand, CommandError

from common.errors import ApiError

from ...services import statements


class Command(BaseCommand):
    help = "Mark a Tenantly invoice paid, with the payment's reference."

    def add_arguments(self, parser: Any) -> None:
        parser.add_argument("number", help="TNT-000123")
        parser.add_argument("--ref", required=True, help="Bank reference or note, kept on the invoice.")

    def handle(self, *args: Any, **options: Any) -> None:  # noqa: ARG002
        try:
            invoice = statements.mark_paid(statements.by_code(options["number"]).id, "manual", options["ref"])
        except ApiError as e:
            raise CommandError(e.detail) from e
        self.stdout.write(f"{invoice.code}: {invoice.status} ({invoice.total} {invoice.currency})")
