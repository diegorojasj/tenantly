from django.urls import path
from src.controllers import api

urlpatterns = [path("", api.urls)]
