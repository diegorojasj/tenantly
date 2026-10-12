"""Renew periods, invoice the ones past their grace, charge cards and chase unpaid invoices.

Idempotent: run it hourly or daily; `--loop` keeps it running in a container.
"""

from __future__ import annotations

import time
from typing import Any

from django.core.management.base import BaseCommand

from ...services import cycle


class Command(BaseCommand):
    help = "Run the Tenantly billing cycle (renewals, invoices, card charges, collections)."

    def add_arguments(self, parser: Any) -> None:
        parser.add_argument("--loop", type=int, default=0, metavar="SECONDS", help="Repeat every N seconds.")

    def handle(self, *args: Any, **options: Any) -> None:  # noqa: ARG002
        while True:
            done = cycle.run()
            if any(done.values()):
                self.stdout.write(" ".join(f"{k}={v}" for k, v in done.items()))
            if not options["loop"]:
                return
            time.sleep(options["loop"])
