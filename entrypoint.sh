#!/bin/sh
set -e

# wait until the database accepts connections. On a cold start MySQL
# initialises its data directory for 30–40 seconds, so a fixed pause is
# either too short or wasted time.
echo "waiting for database at ${DB_HOST}:${DB_PORT}..."
until mysqladmin ping -h "${DB_HOST}" -P "${DB_PORT}" --silent 2>/dev/null; do
    sleep 2
done
echo "database is up"

python manage.py migrate --noinput

# idempotent, hence safe to run on every start
python manage.py init_groups

# exchange rates are required, otherwise price_base is computed incorrectly
python manage.py update_rates || echo "update_rates failed, continuing"

exec "$@"