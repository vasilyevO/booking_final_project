# RU: Этап 1 — сборка колёс. Компиляторы и заголовки нужны только здесь
#     и в финальный образ не попадут (тема 22: Multi-Stage Build).
# EN: Stage 1 — building wheels. Compilers and headers are needed only here
#     and never reach the final image (Multi-Stage Build).
FROM python:3.13-slim AS builder

RUN apt-get update && apt-get install -y --no-install-recommends \
        build-essential \
        default-libmysqlclient-dev \
        pkg-config \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /build

# RU: КЛЮЧЕВОЕ. requirements.txt копируется ОТДЕЛЬНО и раньше кода.
#     Docker кэширует слои: пока этот файл не менялся, слой с установкой
#     берётся из кэша. При COPY . . перед pip install любая правка во
#     views.py заставляла бы пересобирать все зависимости заново.
# EN: THE KEY POINT. requirements.txt is copied SEPARATELY and before the code.
#     Docker caches layers: while this file is unchanged the install layer comes
#     from cache. With COPY . . before pip install, any edit in views.py would
#     rebuild every dependency from scratch.
COPY requirements.txt .
RUN pip wheel --no-cache-dir --wheel-dir /build/wheels -r requirements.txt


# RU: Этап 2 — рантайм. Только runtime-библиотека MySQL и gettext для
#     компиляции переводов. Компиляторов здесь нет.
# EN: Stage 2 — runtime. Only the MySQL runtime library and gettext for
#     compiling translations. No compilers here.
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

COPY . .

# RU: compilemessages ОБЯЗАТЕЛЕН на этапе сборки: файлы .mo лежат в
#     .gitignore, значит в образ они не попадают, и без этой команды вся
#     локализация в контейнере молча не работает — без единой ошибки.
# EN: compilemessages is MANDATORY at build time: the .mo files are gitignored,
#     so they never reach the image, and without this command all localisation
#     silently fails inside the container — with no error at all.
RUN python manage.py compilemessages

# RU: collectstatic собирает админку и Swagger UI. При DEBUG=False Django
#     статику не отдаёт — её будет раздавать nginx из общего тома.
# EN: collectstatic gathers the admin and Swagger UI assets. With DEBUG=False
#     Django serves no static files — nginx will serve them from a shared volume.
RUN SECRET_KEY=build-only DB_NAME=x DB_USER=x DB_PASSWORD=x \
    python manage.py collectstatic --noinput

# RU: непривилегированный пользователь. Процесс в контейнере под root — это
#     root на хосте при побеге из контейнера.
# EN: an unprivileged user. A root process inside the container is root on the
#     host if the container is escaped.
RUN useradd --create-home --uid 1000 appuser \
    && mkdir -p /app/media /app/logs \
    && chown -R appuser:appuser /app
USER appuser

COPY --chown=appuser:appuser entrypoint.sh /app/entrypoint.sh

EXPOSE 8000

ENTRYPOINT ["/app/entrypoint.sh"]
# RU: gunicorn, а не runserver. runserver однопоточный и отладочный,
#     документация Django прямо запрещает его в продакшене.
#     config.wsgi — имя ЕГО пакета, не core.wsgi из чужого примера.
# EN: gunicorn, not runserver. runserver is single-threaded and for debugging;
#     the Django docs explicitly forbid it in production.
#     config.wsgi is THIS project's package, not core.wsgi from someone's sample.
CMD ["gunicorn", "config.wsgi:application", \
     "--bind", "0.0.0.0:8000", \
     "--workers", "3", \
     "--timeout", "60", \
     "--access-logfile", "-", \
     "--error-logfile", "-"]