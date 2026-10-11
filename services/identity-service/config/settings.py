"""Identity service: accounts, businesses, the location tree, team, audit trail."""

import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR.parent))

from common.settings import build  # noqa: E402

globals().update(build(service="identity", base_dir=BASE_DIR, apps=["src.apps.IdentityConfig"]))

SESSION_TTL_DAYS = 30
