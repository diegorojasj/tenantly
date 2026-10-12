from common.api import create_api

from .account import router as account_router
from .admin import router as admin_router
from .internal import router as internal_router
from .tenant import router as tenant_router

api = create_api("Tenantly identity")
api.add_router("/", account_router)
api.add_router("/tenant", tenant_router)
api.add_router("/admin", admin_router)
api.add_router("/internal", internal_router)

__all__ = ["api"]
