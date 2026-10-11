"""Billing service: what customers owe and pay, revenue, the tenant's Tenantly plan."""

import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR.parent))

from common.settings import build  # noqa: E402

globals().update(build(service="billing", base_dir=BASE_DIR, apps=["src.apps.BillingConfig"]))

# Charges still unpaid after this many days read as overdue.
OVERDUE_AFTER_DAYS = 14
