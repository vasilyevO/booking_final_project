#!/bin/sh
set -e

# RU: ждём готовности БД по-настоящему, а не sleep 15. На холодном старте
#     MySQL инициализирует каталог данных 30–40 секунд, и фиксированная
#     пауза либо коротка, либо тратится впустую.
# EN: wait for the database for real instead of sleep 15. On a cold start MySQL
#     initialises its data directory for 30–40 seconds, so a fixed pause is
#     either too short or plain wasted time.
echo "waiting for database at ${DB_HOST}:${DB_PORT}..."
until mysqladmin ping -h "${DB_HOST}" -P "${DB_PORT}" --silent 2>/dev/null; do
    sleep 2
done
echo "database is up"

python manage.py migrate --noinput

# RU: идемпотентна, поэтому безопасна при каждом старте
# EN: idempotent, hence safe to run on every start
python manage.py init_groups

# RU: курсы валют нужны, иначе price_base посчитается неверно
# EN: exchange rates are required, otherwise price_base is computed incorrectly
python manage.py update_rates || echo "update_rates failed, continuing"

exec "$@"