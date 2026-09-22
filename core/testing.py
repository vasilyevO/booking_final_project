"""
Shared factories and base classes for the test suite.

Kept outside the tests packages so every app can import them without
cross-app test imports.
"""
from __future__ import annotations

import itertools
from io import StringIO
from datetime import timedelta
from decimal import Decimal

from django.contrib.auth.models import Group
from django.core.cache import cache
from django.core.management import call_command
from django.test import TestCase, TransactionTestCase
from django.utils import timezone
from djmoney.money import Money
from rest_framework.test import APIClient

from apps.bookings.models import Booking, BookingStatus
from apps.listings.models import Listing, PropertyType
from apps.reviews.models import Review
from apps.users.models import User

PASSWORD = "Str0ng-pass-123"

_seq = itertools.count(1)


def today():
    return timezone.localdate()


def make_user(*, group: str | None = None, email: str | None = None, **extra) -> User:
    """A user, optionally added to a role group created by init_groups."""
    email = email or f"user{next(_seq)}@example.com"
    user = User.objects.create_user(email=email, password=PASSWORD, **extra)
    if group:
        user.groups.add(Group.objects.get(name=group))
    return user


def make_listing(owner: User, **extra) -> Listing:
    data = {
        "title": "Bright flat near the river",
        "description": "Two rooms, balcony and a quiet courtyard.",
        "city": "Köln",
        "price_per_night": Money(Decimal("100.00"), "EUR"),
        "rooms": 2,
        "property_type": PropertyType.APARTMENT,
    }
    data.update(extra)
    return Listing.objects.create(owner=owner, **data)


def make_booking(
    listing: Listing,
    tenant: User,
    *,
    start_offset: int = 10,
    nights: int = 3,
    status: str = BookingStatus.PENDING,
) -> Booking:
    """
    A booking relative to today. Past or non-pending bookings are saved with
    skip_validation, the same way historical rows would be imported.
    """
    start = today() + timedelta(days=start_offset)
    booking = Booking(
        listing=listing,
        tenant=tenant,
        start_date=start,
        end_date=start + timedelta(days=nights),
        status=status,
        price_per_night_snapshot=listing.price_per_night,
        listing_title_snapshot=listing.title,
    )
    booking.total_price = booking.calculate_total()
    booking.total_price_base = booking.total_price.amount
    if start_offset < 0 or status != BookingStatus.PENDING:
        booking.save(skip_validation=True)
    else:
        booking.save()
    # behave like a row loaded from the database
    booking._original_status = booking.status
    return booking


def make_completed_booking(listing: Listing, tenant: User, *, days_ago: int = 5) -> Booking:
    return make_booking(
        listing, tenant,
        start_offset=-(days_ago + 3), nights=3, status=BookingStatus.COMPLETED,
    )


def make_review(booking: Booking, **extra) -> Review:
    data = {"rating": 5, "text": "Great stay."}
    data.update(extra)
    return Review.objects.create(booking=booking, **data)


class BaseTestCase(TestCase):
    """Creates role groups and exchange rates once per test class."""

    @classmethod
    def setUpTestData(cls):
        call_command("init_groups", stdout=StringIO())
        call_command("update_rates", stdout=StringIO())

    def setUp(self):
        super().setUp()
        # djmoney caches exchange rates; a rate cached by one test must not
        # leak into another
        cache.clear()


class APITestCase(BaseTestCase):
    """BaseTestCase with a DRF client and authentication helpers."""

    def setUp(self):
        super().setUp()
        self.client = APIClient()

    def login(self, user: User | None) -> None:
        self.client.force_authenticate(user=user)


class FullTextTestCase(TransactionTestCase):
    """
    RU: База для тестов, которым нужен настоящий COMMIT.
        InnoDB обновляет FULLTEXT-индекс при коммите транзакции: токены
        новых строк попадают в кэш индекса только тогда. Обычный TestCase
        держит каждый тест в транзакции и откатывает её, поэтому
        MATCH ... AGAINST не видит вставленные строки и возвращает пусто.
        TransactionTestCase коммитит по-настоящему и чистит таблицы после
        теста — медленнее, но это единственный способ проверить FULLTEXT.
    EN: Base for tests that need a real COMMIT.
        InnoDB updates the FULLTEXT index on transaction commit: tokens of
        new rows reach the index cache only then. A plain TestCase keeps
        each test inside a transaction and rolls it back, so
        MATCH ... AGAINST cannot see the inserted rows and returns nothing.
        TransactionTestCase commits for real and truncates the tables
        afterwards — slower, but the only way to exercise FULLTEXT.
    """

    def setUp(self):
        super().setUp()
        # RU: setUpTestData у TransactionTestCase нет — данные не переживают
        #     тест, поэтому подготовка идёт в setUp для каждого.
        # EN: TransactionTestCase has no setUpTestData — data does not survive
        #     a test, so the setup runs in setUp for every one of them.
        call_command("init_groups", stdout=StringIO())
        call_command("update_rates", stdout=StringIO())
        cache.clear()


class FullTextAPITestCase(FullTextTestCase):
    """FullTextTestCase with a DRF client."""

    def setUp(self):
        super().setUp()
        self.client = APIClient()

    def login(self, user: User | None) -> None:
        self.client.force_authenticate(user=user)
