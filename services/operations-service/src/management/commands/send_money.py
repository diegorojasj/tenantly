"""Retry charges and refunds that couldn't reach billing when they were made.

Run it on a schedule (e.g. every minute); `--loop` keeps it running in a container.
"""

from __future__ import annotations

import time
from typing import Any

from django.core.management.base import BaseCommand

from ...services.money import dispatch


class Command(BaseCommand):
    help = "Send pending money events to the billing service."

    def add_arguments(self, parser: Any) -> None:
        parser.add_argument("--loop", type=int, default=0, metavar="SECONDS", help="Repeat every N seconds.")

    def handle(self, *args: Any, **options: Any) -> None:  # noqa: ARG002
        while True:
            sent = dispatch()
            if sent:
                self.stdout.write(f"sent {sent} money event(s)")
            if not options["loop"]:
                return
            time.sleep(options["loop"])
