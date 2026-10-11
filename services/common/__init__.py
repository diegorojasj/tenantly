"""Shared building blocks for every Tenantly service.

Each service is its own Django project (``<name>-service/config``) with its own
database. What they share lives here: settings, error handling, camelCase API
schemas, tenant-token authentication and service-to-service calls.
"""
