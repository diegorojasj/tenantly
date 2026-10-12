"""Block every Tenantly admin whose access window has passed, and log it.

Housekeeping only: every sign-in and admin request checks the window itself. `--loop` keeps
it running in a container.
"""

from __future__ import annotations

import time
from typing import Any

from django.core.management.base import BaseCommand

from ...services import admins


class Command(BaseCommand):
    help = "Block Tenantly admins whose access window has passed."

    def add_arguments(self, parser: Any) -> None:
        parser.add_argument("--loop", type=int, default=0, metavar="SECONDS", help="Repeat every N seconds.")

    def handle(self, *args: Any, **options: Any) -> None:  # noqa: ARG002
        while True:
            expired = admins.expire_overdue()
            if expired or not options["loop"]:
                self.stdout.write(f"expired={expired}")
            if not options["loop"]:
                return
            time.sleep(options["loop"])
