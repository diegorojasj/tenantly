from common.api import create_api

from .bookings import router as bookings_router
from .setup import router as setup_router

api = create_api("Tenantly operations")
api.add_router("/", bookings_router)
api.add_router("/", setup_router)

__all__ = ["api"]
