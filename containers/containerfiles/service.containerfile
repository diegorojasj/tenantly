# One image recipe for every Python service; SERVICE picks which one.
#   build context: ./services   (so the shared `common` package is included)
FROM python:3.13-slim

ARG SERVICE
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/srv \
    HOME=/tmp \
    SERVICE=${SERVICE}

WORKDIR /srv
RUN pip install --no-cache-dir uv
COPY pyproject.toml /srv/pyproject.toml
RUN uv pip install --system --no-cache -r pyproject.toml

COPY common /srv/common
COPY ${SERVICE}-service /srv/app
WORKDIR /srv/app

RUN useradd --system --no-create-home tenantly && chown -R tenantly /srv/app
USER tenantly
EXPOSE 8000

# Migrations are idempotent; run them on every start, then serve.
CMD ["sh", "-c", "python manage.py migrate --noinput && exec gunicorn config.wsgi --bind 0.0.0.0:8000 --workers ${GUNICORN_WORKERS:-3} --access-logfile -"]
