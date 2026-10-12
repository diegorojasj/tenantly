"""Settings shared by every service; each `config/settings.py` calls `build`."""

from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlparse

from .i18n import DEFAULT, LANGUAGES


def env(name: str, default: str = "") -> str:
    return os.environ.get(name, default)


def testing() -> bool:
    return bool(env("TESTING")) or "pytest" in sys.modules


def database_from_url(url: str, base_dir: Path) -> dict[str, Any]:
    """`postgres://user:pass@host:5432/name` -> Django DATABASES entry.

    No URL means a local SQLite file, so tests and quick local runs need nothing installed.
    """
    if not url:
        return {"ENGINE": "django.db.backends.sqlite3", "NAME": str(base_dir / "db.sqlite3")}
    parsed = urlparse(url)
    if parsed.scheme not in {"postgres", "postgresql"}:
        msg = f"Unsupported DATABASE_URL scheme: {parsed.scheme}"
        raise ValueError(msg)
    return {
        "ENGINE": "django.db.backends.postgresql",
        "NAME": parsed.path.lstrip("/"),
        "USER": unquote(parsed.username or ""),
        "PASSWORD": unquote(parsed.password or ""),
        "HOST": parsed.hostname or "localhost",
        "PORT": str(parsed.port or 5432),
        "CONN_MAX_AGE": 60,
        "CONN_HEALTH_CHECKS": True,
    }


def build(*, service: str, base_dir: Path, apps: list[str]) -> dict[str, Any]:
    debug = env("DEBUG", "0") == "1"
    secret = env("DJANGO_SECRET_KEY") or ("insecure-dev-key-" + service if debug or testing() else "")
    if not secret:
        msg = "DJANGO_SECRET_KEY is not set"
        raise RuntimeError(msg)
    return {
        "SERVICE_NAME": service,
        "BASE_DIR": base_dir,
        "SECRET_KEY": secret,
        "DEBUG": debug,
        "ALLOWED_HOSTS": [h.strip() for h in env("ALLOWED_HOSTS", "*").split(",") if h.strip()],
        "INSTALLED_APPS": ["django.contrib.contenttypes", "django.contrib.auth", *apps],
        "MIDDLEWARE": [
            "django.middleware.security.SecurityMiddleware",
            # Answers in the caller's Accept-Language (common/i18n.py).
            "django.middleware.locale.LocaleMiddleware",
            "django.middleware.common.CommonMiddleware",
        ],
        "ROOT_URLCONF": "config.urls",
        "WSGI_APPLICATION": "config.wsgi.application",
        "DATABASES": {"default": database_from_url(env("DATABASE_URL"), base_dir)},
        "DEFAULT_AUTO_FIELD": "django.db.models.BigAutoField",
        "USE_TZ": True,
        "TIME_ZONE": "UTC",
        "LANGUAGE_CODE": DEFAULT,
        "LANGUAGES": LANGUAGES,
        "USE_I18N": True,
        # Shared messages; each service's own catalog is its app's `src/locale`.
        "LOCALE_PATHS": [Path(__file__).resolve().parent / "locale"],
        "PASSWORD_HASHERS": [
            "django.contrib.auth.hashers.PBKDF2PasswordHasher",
        ],
        # Shared between services: tenant-token signing key and the internal-call key.
        "JWT_SECRET": env("JWT_SECRET", "test-jwt-secret-test-jwt-secret!" if testing() else ""),
        # Tenantly admin tokens (identity only): a key of their own, never JWT_SECRET.
        "ADMIN_JWT_SECRET": env("ADMIN_JWT_SECRET", "test-admin-secret-test-admin-secret" if testing() else ""),
        # How long `manage.py activate_admin` opens an admin's access window for.
        "ADMIN_WINDOW_MINUTES": int(env("ADMIN_WINDOW_MINUTES", "10")),
        "INTERNAL_TOKEN": env("INTERNAL_TOKEN", "test-internal-token" if testing() else ""),
        # Where the other services live (inside the network, not through the proxy).
        "IDENTITY_URL": env("IDENTITY_URL", "http://identity.test"),
        "OPERATIONS_URL": env("OPERATIONS_URL", "http://operations.test"),
        "BILLING_URL": env("BILLING_URL", "http://billing.test"),
        "LOGGING": {
            "version": 1,
            "disable_existing_loggers": False,
            "handlers": {"console": {"class": "logging.StreamHandler"}},
            "root": {"handlers": ["console"], "level": env("LOG_LEVEL", "INFO")},
        },
    }
