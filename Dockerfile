# Stage 1 — building wheels. Compilers and headers are needed only here
# and never reach the final image (Multi-Stage Build).
FROM python:3.13-slim AS builder

RUN apt-get update && apt-get install -y --no-install-recommends \
        build-essential \
        default-libmysqlclient-dev \
        pkg-config \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /build

# requirements.txt is copied separately and before the code, so the install
# layer stays cached until the dependencies change. Copying the code first
# would reinstall every dependency on each source edit.
COPY requirements.txt .
RUN pip wheel --no-cache-dir --wheel-dir /build/wheels -r requirements.txt


# Stage 2 — runtime. Only the MySQL runtime library and gettext for
# compiling translations. No compilers here.
FROM python:3.13-slim

RUN apt-get update && apt-get install -y --no-install-recommends \
        default-mysql-client \
        libmariadb3 \
        gettext \
    && rm -rf /var/lib/apt/lists/*

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    IN_CONTAINER=True

WORKDIR /app

COPY --from=builder /build/wheels /wheels
RUN pip install --no-cache-dir /wheels/* && rm -rf /wheels

# create the directories before the first manage.py command — settings.py
# may try to open the log file at import time.
RUN mkdir -p /app/media /app/logs /app/staticfiles

COPY . .

RUN SECRET_KEY=build-only DB_NAME=x DB_USER=x DB_PASSWORD=x LOG_TO_FILE=False \
    sh -c "python manage.py compilemessages && python manage.py collectstatic --noinput"

RUN useradd --create-home --uid 1000 appuser \
    && chown -R appuser:appuser /app
USER appuser

COPY --chown=appuser:appuser entrypoint.sh /app/entrypoint.sh

EXPOSE 8000

ENTRYPOINT ["/app/entrypoint.sh"]
# gunicorn, not runserver. runserver is single-threaded and for debugging;
# the Django docs advise against it in production.
CMD ["gunicorn", "config.wsgi:application", \
     "--bind", "0.0.0.0:8000", \
     "--workers", "3", \
     "--timeout", "60", \
     "--access-logfile", "-", \
     "--error-logfile", "-"]