from __future__ import annotations

import unittest
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db import connection
from django.utils import translation
from djmoney.contrib.exchange.models import Rate
from djmoney.money import Money

from apps.bookings.models import BookingStatus
from apps.listings.exchange import StaticExchangeBackend
from apps.listings.models import Listing, ListingPhoto, ListingQuerySet, listing_photo_path
from apps.listings.services import POSITION_STEP, reorder_photos
from core.testing import BaseTestCase, make_booking, make_listing, make_user


class ListingSaveTests(BaseTestCase):
    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        cls.owner = make_user(group="landlords")

    def test_city_is_normalised_for_search(self):
        listing = make_listing(self.owner, city="Köln")
        self.assertEqual(listing.city, "Köln")
        self.assertEqual(listing.city_normalized, "koeln")

    def test_price_base_in_base_currency(self):
        listing = make_listing(self.owner, price_per_night=Money("80.00", "EUR"))
        self.assertEqual(listing.price_base, Decimal("80.00"))

    def test_price_base_is_converted_and_rounded(self):
        listing = make_listing(self.owner, price_per_night=Money("250.00", "CZK"))
        # 250 / 25.10 = 9.9601...
        self.assertEqual(listing.price_base, Decimal("9.96"))

    def test_price_base_falls_back_without_rates(self):
        Rate.objects.all().delete()
        listing = make_listing(self.owner, price_per_night=Money("109.00", "USD"))
        self.assertEqual(listing.price_base, Decimal("109.00"))

    def test_partial_save_updates_derived_fields(self):
        listing = make_listing(self.owner)
        listing.city = "München"
        listing.price_per_night = Money("109.00", "USD")
        listing.save(update_fields=["city", "price_per_night", "price_per_night_currency"])
        listing.refresh_from_db()
        self.assertEqual(listing.city_normalized, "muenchen")
        self.assertEqual(listing.price_base, Decimal("100.00"))

    def test_invalid_values_are_rejected(self):
        cases = {
            "rooms": {"rooms": 0},
            "price_per_night": {"price_per_night": Money("0", "EUR")},
            "property_type": {"property_type": "castle"},
        }
        for field, extra in cases.items():
            with self.subTest(field=field), self.assertRaises(ValidationError) as ctx:
                make_listing(self.owner, **extra)
            self.assertIn(field, ctx.exception.message_dict)

    def test_unsupported_currency_is_rejected(self):
        with self.assertRaises(ValidationError):
            make_listing(self.owner, price_per_night=Money("10", "JPY"))

    def test_history_is_recorded(self):
        listing = make_listing(self.owner)
        listing.title = "Renamed"
        listing.save()
        self.assertEqual(listing.history.count(), 2)
        self.assertEqual(listing.history.first().title, "Renamed")

    def test_str(self):
        self.assertEqual(str(make_listing(self.owner, title="Flat", city="Bonn")), "Flat (Bonn)")

    def test_has_future_bookings(self):
        listing = make_listing(self.owner)
        tenant = make_user()
        self.assertFalse(listing.has_future_bookings())
        make_booking(listing, tenant, start_offset=-10, nights=2, status=BookingStatus.COMPLETED)
        self.assertFalse(listing.has_future_bookings())
        make_booking(listing, tenant, start_offset=5)
        self.assertTrue(listing.has_future_bookings())


class ListingQuerySetTests(BaseTestCase):
    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        cls.owner = make_user()
        cls.river = make_listing(cls.owner, title="Flat near the river", description="Quiet.")
        cls.garden = make_listing(
            cls.owner, title="House", description="Large garden and a sauna.", is_active=False
        )

    def test_active_and_by_owner(self):
        self.assertEqual(list(Listing.objects.active()), [self.river])
        self.assertEqual(Listing.objects.by_owner(self.owner).count(), 2)
        self.assertEqual(Listing.objects.by_owner(make_user()).count(), 0)

    def test_search_title_and_description(self):
        self.assertEqual(list(Listing.objects.search("river")), [self.river])
        self.assertEqual(list(Listing.objects.search("garden")), [self.garden])

    def test_short_term_uses_substring_match(self):
        self.assertEqual(list(Listing.objects.search("sa")), [self.garden])

    def test_blank_search_returns_everything(self):
        self.assertEqual(Listing.objects.search("  ").count(), 2)

    def test_search_uses_active_language_columns(self):
        self.river.title_de = "Wohnung am Fluss"
        self.river.save()
        with translation.override("de"):
            self.assertEqual(list(Listing.objects.search("Fluss")), [self.river])
        with translation.override("en"):
            self.assertEqual(list(Listing.objects.search("Fluss")), [])

    def test_boolean_phrases_neutralise_operators(self):
        phrases = ListingQuerySet._as_boolean_phrases('++a -b "c" (d*)')
        self.assertEqual(phrases, '"++a" "-b" "c" "(d*)"')
        self.assertEqual(ListingQuerySet._as_boolean_phrases('""'), "")

    @unittest.skipUnless(connection.vendor == "mysql", "FULLTEXT search requires MySQL")
    def test_fulltext_search_survives_operators(self):
        self.assertEqual(list(Listing.objects.search("++river")), [])
        self.assertEqual(list(Listing.objects.search("river")), [self.river])


class ListingPhotoTests(BaseTestCase):
    def test_upload_path_is_unique_per_file(self):
        photo = ListingPhoto(listing_id=7)
        first = listing_photo_path(photo, "Photo.JPG")
        second = listing_photo_path(photo, "Photo.JPG")
        self.assertTrue(first.startswith("listings/7/"))
        self.assertTrue(first.endswith(".jpg"))
        self.assertNotEqual(first, second)

    def test_reorder_photos(self):
        listing = make_listing(make_user())
        photos = [
            ListingPhoto.objects.create(listing=listing, image=f"x{i}.jpg", position=i)
            for i in range(3)
        ]
        new_order = [photos[2].pk, photos[0].pk, photos[1].pk]
        reorder_photos(listing=listing, photo_ids=new_order)
        self.assertEqual(list(listing.photos.values_list("pk", flat=True)), new_order)
        self.assertEqual(
            list(listing.photos.values_list("position", flat=True)),
            [POSITION_STEP, 2 * POSITION_STEP, 3 * POSITION_STEP],
        )

    def test_reorder_rejects_foreign_or_missing_ids(self):
        listing = make_listing(make_user())
        photo = ListingPhoto.objects.create(listing=listing, image="x.jpg")
        other = ListingPhoto.objects.create(listing=make_listing(make_user()), image="y.jpg")
        for ids in ([photo.pk, other.pk], []):
            with self.subTest(ids=ids), self.assertRaises(ValidationError):
                reorder_photos(listing=listing, photo_ids=ids)


class StaticExchangeBackendTests(BaseTestCase):
    def test_update_rates_is_idempotent(self):
        backend = StaticExchangeBackend()
        backend.update_rates()
        backend.update_rates()
        rates = dict(Rate.objects.filter(backend="static").values_list("currency", "value"))
        self.assertEqual(rates["USD"], Decimal("1.09"))
        self.assertEqual(len(rates), len(StaticExchangeBackend.RATES))
