# Booking API

REST API for a short-term housing rental service: landlords publish listings,
tenants search and book them, and leave reviews after the stay.

Built with Django 6.1, Django REST Framework and MySQL 8.4.

## Features

- **Users** — email login with JWT. Roles are Django groups: `tenants` book
  and review, `landlords` publish listings and handle booking requests.
- **Listings** — CRUD for owners, soft deletion, photos with manual ordering,
  titles and descriptions in English, German and Russian.
- **Search** — MySQL FULLTEXT search in the request language, filters by city
  (any spelling: `Köln`, `Koeln`, `koln`), price, rooms and property type.
  Prices are stored in five currencies and filtered and sorted in EUR.
- **Bookings** — overlap protection under a row lock, a status state machine
  (`pending → confirmed/rejected/cancelled`, `confirmed → completed/cancelled`),
  frozen price and exchange rate, email notifications in each recipient's language.
- **Reviews** — only for completed stays, editable by the author for
  `REVIEW_EDIT_WINDOW_DAYS`, never deleted by users.
- **Analytics** — de-duplicated listing views, popular search keywords and
  most viewed listings.
- **Operations** — change history (django-simple-history), request ids in
  every log line, an N+1 query warning in development.

## Roles and permissions

Roles are Django groups created by `init_groups`. Group permissions answer
*may this user perform the action at all*; object checks answer *is this
object theirs*. Both must pass.

| Action | Anonymous | Tenant | Landlord (owner) | Staff |
| --- | --- | --- | --- | --- |
| Browse listings and reviews | yes | yes | yes | yes |
| Create a listing | — | — | yes | yes |
| Edit or delete a listing | — | — | own only | yes |
| Create a booking | — | yes | — ¹ | yes |
| View a booking | — | own | on own listings | all |
| Confirm or reject | — | — | on own listings | yes |
| Cancel | — | own, before deadline | on own listings | yes |
| Complete | — | — | — | `complete_bookings` only |
| Write a review | — | after a completed stay | — | — |
| Delete a review | — | — | — | soft delete only |

¹ A landlord who also wants to rent is added to both groups. Booking one's
own listing is rejected by the model regardless of groups.

## Running with Docker

```sh
cp .env.example .env        # then set SECRET_KEY and the passwords
docker compose up --build
```

The entrypoint waits for MySQL, applies migrations, creates the role groups and
loads exchange rates. The API is served by gunicorn behind nginx on port 80.

Optional demo data (users share the password `demo-pass-2024`):

```sh
docker compose exec web python manage.py seed_demo --flush
```

## Running locally

```sh
python -m venv .venv
.venv/Scripts/activate      # Windows; use .venv/bin/activate elsewhere
pip install -r requirements.txt
cp .env.example .env        # point DB_* at a running MySQL 8.4

python manage.py migrate
python manage.py init_groups
python manage.py update_rates
python manage.py compilemessages
python manage.py runserver
```

Set `DB_ENGINE=sqlite` to use a local SQLite file instead of MySQL. FULLTEXT
indexes are skipped and search falls back to a substring match.

## API

| Path | Description |
| --- | --- |
| `/api/docs/` | Swagger UI |
| `/api/redoc/` | ReDoc |
| `/api/schema/` | OpenAPI schema (also committed as `schema.yml`) |
| `/api/auth/token/`, `/api/auth/token/refresh/` | JWT obtain and refresh |
| `/api/users/register/`, `/api/users/me/` | Registration and own profile |
| `/api/listings/` | Listings, `photos/`, `photos/reorder/`, `reviews/` actions |
| `/api/bookings/` | Bookings, `confirm/`, `reject/`, `cancel/` actions |
| `/api/reviews/` | Reviews |
| `/api/analytics/popular-keywords/`, `/api/analytics/popular-listings/` | Analytics |

Regenerate the committed schema after API changes:

```sh
python manage.py spectacular --file schema.yml
```

## Deployment to AWS EC2

The same `docker-compose.yml` runs in production: MySQL, gunicorn and nginx
in three containers. The database port is not published — services reach
each other by name inside the Compose network.

1. Launch an instance: Amazon Linux 2023, `t3.micro`, 20 GiB gp3.
   Paste `deploy/bootstrap.sh` into *User data* — it installs Docker,
   the Compose and Buildx plugins and a 1 GiB swap file (the image build
   compiles `mysqlclient` and runs out of memory without it).
2. Security group: port 22 from your IP only, port 80 from anywhere.
   Do **not** open 3306.
3. Connect and deploy:

   ```sh
   ssh -i ~/.ssh/<key>.pem ec2-user@<public-ip>
   cd /opt/booking
   git clone <repository-url> .
   nano .env                    # see the production values below
   docker compose up -d --build
   docker compose exec web python manage.py createsuperuser
   ```

4. Open `http://<public-ip>/api/docs/`.

Production `.env` differs from the local one in:

| Variable | Production value |
| --- | --- |
| `DEBUG` | `False` |
| `SECRET_KEY` | a new key: `openssl rand -hex 32` |
| `ALLOWED_HOSTS` | the public IP and DNS name of the instance |
| `CSRF_TRUSTED_ORIGINS` | `http://<public-ip>` (scheme required) |
| `SITE_URL` | `http://<public-ip>` |
| `DB_PASSWORD`, `DB_ROOT_PASSWORD` | new, different values |
| `LOG_TO_FILE` | `False` — containers log to stdout |

Avoid `$` in any value: Compose treats it as variable substitution and
silently truncates the string. `openssl rand -hex` never produces one.

MySQL reads `MYSQL_*` variables only when its volume is empty. Changing a
database password later requires `docker compose down -v`, which deletes
the data.

Update after a `git push`:

```sh
git pull
docker compose up -d --build   # migrations run in the entrypoint
```

Without an Elastic IP the public address changes after every stop/start —
update the three address variables in `.env` and run `docker compose up -d`.

## Management commands

| Command | Purpose |
| --- | --- |
| `init_groups` | Create the `tenants` and `landlords` groups with their permissions. Idempotent. |
| `update_rates` | Load exchange rates from `EXCHANGE_BACKEND` (fixed rates by default). |
| `complete_bookings` | Mark confirmed bookings as completed after check-out. Run daily. |
| `seed_demo` | Generate demo users, listings, bookings, reviews and analytics. |

## Configuration

All settings come from environment variables, see `.env.example`.
Besides the database and `SECRET_KEY`:

| Variable | Default | Meaning |
| --- | --- | --- |
| `DB_ENGINE` | `mysql` | `sqlite` for a local SQLite database |
| `ALLOWED_HOSTS` | `localhost,127.0.0.1` | Comma-separated host names |
| `CSRF_TRUSTED_ORIGINS` | `http://localhost` | Origins with scheme, comma-separated |
| `BOOKING_CANCELLATION_DAYS` | `1` | Days before check-in a booking can still be cancelled |
| `REVIEW_EDIT_WINDOW_DAYS` | `14` | Days after posting a review can be edited |
| `EMAIL_BACKEND` | console | Django email backend path |
| `SITE_URL` | `http://127.0.0.1:8000` | Base URL used in email links |
| `LOG_LEVEL`, `LOG_TO_FILE`, `LOG_SQL` | `INFO`, on, off | Logging |
| `QUERY_COUNT_WARNING` | `20` | Queries per request before an N+1 warning (DEBUG only) |

## Tests

```sh
python manage.py test                      # against MySQL from .env
DB_ENGINE=sqlite python manage.py test     # no MySQL server needed
```

In PowerShell set the variable first: `$env:DB_ENGINE = "sqlite"`.

On MySQL the test runner creates `test_<DB_NAME>`. The application user
has rights on its own database only, so grant them once:

```sh
docker compose exec db mysql -u root -p -e \
  "GRANT ALL PRIVILEGES ON \`test_booking_db\`.* TO 'booking_user'@'%'; FLUSH PRIVILEGES;"
docker compose exec web python manage.py test
```

The FULLTEXT search test runs on MySQL only and is skipped on SQLite.
Shared factories for tests live in `core/testing.py`.

---

# Booking API (русская версия)

REST API сервиса краткосрочной аренды жилья: арендодатели публикуют объявления,
арендаторы ищут и бронируют жильё и оставляют отзывы после проживания.

Стек: Django 6.1, Django REST Framework, MySQL 8.4.

## Возможности

- **Пользователи** — вход по email через JWT. Роли — группы Django: `tenants`
  бронируют и оставляют отзывы, `landlords` публикуют объявления и обрабатывают
  заявки на бронирование.
- **Объявления** — CRUD для владельцев, мягкое удаление, фотографии с ручной
  сортировкой, заголовок и описание на английском, немецком и русском.
- **Поиск** — полнотекстовый поиск MySQL (FULLTEXT) на языке запроса, фильтры по
  городу (в любом написании: `Köln`, `Koeln`, `koln`), цене, числу комнат и типу
  жилья. Цены хранятся в пяти валютах, фильтрация и сортировка идут в EUR.
- **Бронирования** — защита от пересечения дат под блокировкой строки, машина
  состояний (`pending → confirmed/rejected/cancelled`, `confirmed → completed/cancelled`),
  зафиксированные цена и курс, email-уведомления на языке каждого получателя.
- **Отзывы** — только по завершённым проживаниям, автор может править отзыв в
  течение `REVIEW_EDIT_WINDOW_DAYS`, пользователи отзывы не удаляют.
- **Аналитика** — просмотры объявлений без дублей, популярные поисковые запросы
  и самые просматриваемые объявления.
- **Эксплуатация** — история изменений (django-simple-history), id запроса в
  каждой строке лога, предупреждение об N+1 запросах в режиме разработки.

## Запуск в Docker

```sh
cp .env.example .env        # затем задайте SECRET_KEY и пароли
docker compose up --build
```

Entrypoint дожидается MySQL, применяет миграции, создаёт группы ролей и
загружает курсы валют. API обслуживает gunicorn за nginx на порту 80.

Демо-данные по желанию (общий пароль пользователей — `demo-pass-2024`):

```sh
docker compose exec web python manage.py seed_demo --flush
```

## Локальный запуск

```sh
python -m venv .venv
.venv/Scripts/activate      # Windows; в других ОС — .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env        # укажите в DB_* работающий MySQL 8.4

python manage.py migrate
python manage.py init_groups
python manage.py update_rates
python manage.py compilemessages
python manage.py runserver
```

`DB_ENGINE=sqlite` переключает проект на локальный файл SQLite вместо MySQL.
FULLTEXT-индексы при этом не создаются, поиск работает по подстроке.

## API

| Путь | Назначение |
| --- | --- |
| `/api/docs/` | Swagger UI |
| `/api/redoc/` | ReDoc |
| `/api/schema/` | Схема OpenAPI (также лежит в репозитории как `schema.yml`) |
| `/api/auth/token/`, `/api/auth/token/refresh/` | Получение и обновление JWT |
| `/api/users/register/`, `/api/users/me/` | Регистрация и свой профиль |
| `/api/listings/` | Объявления, действия `photos/`, `photos/reorder/`, `reviews/` |
| `/api/bookings/` | Бронирования, действия `confirm/`, `reject/`, `cancel/` |
| `/api/reviews/` | Отзывы |
| `/api/analytics/popular-keywords/`, `/api/analytics/popular-listings/` | Аналитика |

После изменений API пересоздайте схему:

```sh
python manage.py spectacular --file schema.yml
```

## Management-команды

| Команда | Назначение |
| --- | --- |
| `init_groups` | Создаёт группы `tenants` и `landlords` с их правами. Идемпотентна. |
| `update_rates` | Загружает курсы валют из `EXCHANGE_BACKEND` (по умолчанию — фиксированные). |
| `complete_bookings` | Переводит подтверждённые брони в завершённые после даты выезда. Запускать ежедневно. |
| `seed_demo` | Генерирует демо-пользователей, объявления, брони, отзывы и аналитику. |

## Настройки

Все настройки задаются переменными окружения, см. `.env.example`.
Помимо базы данных и `SECRET_KEY`:

| Переменная | По умолчанию | Значение |
| --- | --- | --- |
| `DB_ENGINE` | `mysql` | `sqlite` — локальная база SQLite |
| `BOOKING_CANCELLATION_DAYS` | `1` | За сколько дней до заезда бронь ещё можно отменить |
| `REVIEW_EDIT_WINDOW_DAYS` | `14` | Сколько дней после публикации отзыв можно править |
| `EMAIL_BACKEND` | console | Путь к email-бэкенду Django |
| `SITE_URL` | `http://127.0.0.1:8000` | Базовый URL для ссылок в письмах |
| `LOG_LEVEL`, `LOG_TO_FILE`, `LOG_SQL` | `INFO`, вкл., выкл. | Логирование |
| `QUERY_COUNT_WARNING` | `20` | Число запросов к БД на один HTTP-запрос, после которого пишется предупреждение об N+1 (только при DEBUG) |

## Тесты

```sh
python manage.py test                      # на MySQL из .env
DB_ENGINE=sqlite python manage.py test     # без сервера MySQL
```

В PowerShell сначала задайте переменную: `$env:DB_ENGINE = "sqlite"`.

Тест полнотекстового поиска выполняется только на MySQL, на SQLite он пропускается.
Общие фабрики для тестов находятся в `core/testing.py`.
