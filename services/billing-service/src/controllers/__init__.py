from common.api import create_api

from .internal import router as internal_router
from .tenant import router as tenant_router

api = create_api("Tenantly billing")
api.add_router("/", tenant_router)
api.add_router("/internal", internal_router)

__all__ = ["api"]
