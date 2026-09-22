from __future__ import annotations

import shutil
import tempfile
from io import BytesIO

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import override_settings
from djmoney.money import Money
from PIL import Image

from apps.analytics.models import ListingStats, SearchQuery
from apps.bookings.models import BookingStatus
from apps.listings.models import Listing, ListingPhoto
from core.testing import (
    APITestCase, FullTextAPITestCase, make_booking, make_completed_booking,
    make_listing, make_review, make_user,
)

LIST_URL = "/api/listings/"


def detail_url(listing, suffix=""):
    return f"{LIST_URL}{listing.public_id}/{suffix}"


def image_file(name="photo.jpg"):
    buffer = BytesIO()
    Image.new("RGB", (10, 10), "blue").save(buffer, format="JPEG")
    return SimpleUploadedFile(name, buffer.getvalue(), content_type="image/jpeg")


class ListingReadTests(APITestCase):
    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        cls.owner = make_user(group="landlords")
        cls.other_owner = make_user(group="landlords")
        cls.tenant = make_user(group="tenants")
        cls.staff = make_user(is_staff=True)
        cls.active = make_listing(cls.owner, title="Active flat")
        cls.hidden = make_listing(cls.owner, title="Hidden flat", is_active=False)
        cls.deleted = make_listing(cls.owner, title="Deleted flat")
        cls.deleted.delete()

    def titles(self, response):
        return {item["title"] for item in response.json()["results"]}

    def test_anonymous_sees_active_only(self):
        response = self.client.get(LIST_URL)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.titles(response), {"Active flat"})

    def test_owner_also_sees_own_inactive(self):
        self.login(self.owner)
        self.assertEqual(self.titles(self.client.get(LIST_URL)), {"Active flat", "Hidden flat"})

    def test_other_users_do_not_see_inactive(self):
        self.login(self.other_owner)
        self.assertEqual(self.titles(self.client.get(LIST_URL)), {"Active flat"})

    def test_staff_sees_all_but_deleted(self):
        self.login(self.staff)
        self.assertEqual(self.titles(self.client.get(LIST_URL)), {"Active flat", "Hidden flat"})

    def test_retrieve_hidden_listing_is_404_for_others(self):
        self.assertEqual(self.client.get(detail_url(self.hidden)).status_code, 404)
        self.assertEqual(self.client.get(detail_url(self.deleted)).status_code, 404)

    def test_retrieve_returns_detail_and_counts_view(self):
        self.login(self.tenant)
        response = self.client.get(detail_url(self.active))
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["public_id"], str(self.active.public_id))
        self.assertIn("description", body)
        self.assertEqual(body["price_per_night_currency"], "EUR")
        # the same user on the same day counts once
        self.client.get(detail_url(self.active))
        self.assertEqual(ListingStats.objects.get(listing=self.active).views_count, 1)

    def test_rating_counts_completed_bookings_only(self):
        make_review(make_completed_booking(self.active, self.tenant), rating=4)
        make_review(make_completed_booking(self.active, make_user(), days_ago=20), rating=2)
        item = self.client.get(LIST_URL).json()["results"][0]
        self.assertEqual(item["rating"], 3.0)
        self.assertEqual(item["reviews_count"], 2)

    def test_reviews_action_is_public(self):
        make_review(make_completed_booking(self.active, self.tenant), text="Lovely")
        response = self.client.get(detail_url(self.active, "reviews/"))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["results"][0]["text"], "Lovely")


class ListingFilterTests(APITestCase):
    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        owner = make_user()
        cls.cologne = make_listing(
            owner, title="Cologne", city="Köln", rooms=2, property_type="apartment",
            price_per_night=Money("100.00", "EUR"),
        )
        cls.munich = make_listing(
            owner, title="Munich", city="München", rooms=4, property_type="house",
            price_per_night=Money("218.00", "USD"),  # 200 EUR
        )
        cls.prague = make_listing(
            owner, title="Prague", city="Praha", rooms=1, property_type="studio",
            price_per_night=Money("1255.00", "CZK"),  # 50 EUR
        )

    def titles(self, **params):
        response = self.client.get(LIST_URL, params)
        self.assertEqual(response.status_code, 200)
        return [item["title"] for item in response.json()["results"]]

    def test_city_in_any_spelling(self):
        for spelling in ("Köln", "Koeln", "koln", "KOELN"):
            with self.subTest(spelling=spelling):
                self.assertEqual(self.titles(city=spelling), ["Cologne"])
        self.assertEqual(self.titles(city="Munchen"), ["Munich"])
        self.assertEqual(self.titles(city="Berlin"), [])

    def test_price_range_uses_base_currency(self):
        self.assertEqual(sorted(self.titles(price_max=120)), ["Cologne", "Prague"])
        self.assertEqual(self.titles(price_min=150), ["Munich"])

    def test_rooms_and_type(self):
        self.assertEqual(sorted(self.titles(rooms_min=2)), ["Cologne", "Munich"])
        self.assertEqual(self.titles(rooms_max=1), ["Prague"])
        self.assertEqual(self.titles(property_type="house"), ["Munich"])

    def test_ordering_by_base_price(self):
        self.assertEqual(self.titles(ordering="price_base"), ["Prague", "Cologne", "Munich"])
        self.assertEqual(self.titles(ordering="-price_base"), ["Munich", "Cologne", "Prague"])

    def test_long_search_term_is_truncated(self):
        self.titles(search="x" * 500)
        self.assertEqual(len(SearchQuery.objects.get().keyword), 200)

    def test_listing_without_search_is_not_recorded(self):
        self.titles()
        self.assertFalse(SearchQuery.objects.exists())


class ListingWriteTests(APITestCase):
    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        cls.owner = make_user(group="landlords")
        cls.other_owner = make_user(group="landlords")
        cls.tenant = make_user(group="tenants")

    def payload(self, **overrides):
        data = {
            "title": "New flat",
            "description": "Nice",
            "city": "  Düsseldorf ",
            "price_per_night": "109.00",
            "price_per_night_currency": "USD",
            "rooms": 3,
            "property_type": "apartment",
        }
        data.update(overrides)
        return data

    def test_anonymous_cannot_create(self):
        self.assertEqual(self.client.post(LIST_URL, self.payload(), format="json").status_code, 401)

    def test_tenant_cannot_create(self):
        self.login(self.tenant)
        self.assertEqual(self.client.post(LIST_URL, self.payload(), format="json").status_code, 403)

    def test_landlord_creates_listing_as_owner(self):
        self.login(self.owner)
        response = self.client.post(
            LIST_URL, self.payload(owner=self.other_owner.pk), format="json"
        )
        self.assertEqual(response.status_code, 201)
        listing = Listing.objects.get(public_id=response.json()["public_id"])
        self.assertEqual(listing.owner, self.owner)
        self.assertEqual(listing.city, "Düsseldorf")
        self.assertEqual(listing.city_normalized, "duesseldorf")
        self.assertEqual(str(listing.price_per_night.currency), "USD")
        self.assertEqual(str(listing.price_base), "100.00")

    def test_invalid_payload_is_400(self):
        self.login(self.owner)
        response = self.client.post(LIST_URL, self.payload(rooms=0), format="json")
        self.assertEqual(response.status_code, 400)

    def test_owner_updates_listing(self):
        listing = make_listing(self.owner)
        self.login(self.owner)
        response = self.client.patch(detail_url(listing), {"title": "Updated"}, format="json")
        self.assertEqual(response.status_code, 200)
        listing.refresh_from_db()
        self.assertEqual(listing.title, "Updated")

    def test_other_landlord_cannot_update_or_delete(self):
        listing = make_listing(self.owner)
        self.login(self.other_owner)
        self.assertEqual(
            self.client.patch(detail_url(listing), {"title": "X"}, format="json").status_code, 403
        )
        self.assertEqual(self.client.delete(detail_url(listing)).status_code, 403)

    def test_delete_is_soft(self):
        listing = make_listing(self.owner)
        self.login(self.owner)
        self.assertEqual(self.client.delete(detail_url(listing)).status_code, 204)
        self.assertFalse(Listing.objects.filter(pk=listing.pk).exists())
        self.assertIsNotNone(Listing.all_objects.get(pk=listing.pk).deleted_at)

    def test_delete_keeps_bookings(self):
        listing = make_listing(self.owner)
        booking = make_booking(listing, self.tenant)
        self.login(self.owner)
        self.client.delete(detail_url(listing))
        booking.refresh_from_db()
        self.assertEqual(booking.status, BookingStatus.PENDING)


class ListingPhotoApiTests(APITestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.media_root = tempfile.mkdtemp()
        cls.media_override = override_settings(MEDIA_ROOT=cls.media_root)
        cls.media_override.enable()

    @classmethod
    def tearDownClass(cls):
        cls.media_override.disable()
        shutil.rmtree(cls.media_root, ignore_errors=True)
        super().tearDownClass()

    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        cls.owner = make_user(group="landlords")
        cls.other_owner = make_user(group="landlords")

    def upload(self, listing, **extra):
        return self.client.post(
            detail_url(listing, "photos/"), {"image": image_file(), **extra}, format="multipart"
        )

    def test_owner_uploads_photos_appended_at_the_end(self):
        listing = make_listing(self.owner)
        self.login(self.owner)
        first = self.upload(listing, caption="Living room")
        second = self.upload(listing)
        self.assertEqual(first.status_code, 201)
        self.assertEqual([first.json()["position"], second.json()["position"]], [10, 20])

        card = self.client.get(LIST_URL).json()["results"][0]
        self.assertIn(f"listings/{listing.pk}/", card["cover_photo"])

    def test_other_landlord_cannot_upload(self):
        listing = make_listing(self.owner)
        self.login(self.other_owner)
        self.assertEqual(self.upload(listing).status_code, 403)

    def test_reorder(self):
        listing = make_listing(self.owner)
        a = ListingPhoto.objects.create(listing=listing, image="a.jpg", position=10)
        b = ListingPhoto.objects.create(listing=listing, image="b.jpg", position=20)
        self.login(self.owner)
        response = self.client.post(
            detail_url(listing, "photos/reorder/"), {"photo_ids": [b.pk, a.pk]}, format="json"
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual([item["id"] for item in response.json()], [b.pk, a.pk])

    def test_reorder_with_wrong_ids_is_400(self):
        listing = make_listing(self.owner)
        ListingPhoto.objects.create(listing=listing, image="a.jpg")
        self.login(self.owner)
        response = self.client.post(
            detail_url(listing, "photos/reorder/"), {"photo_ids": [999]}, format="json"
        )
        self.assertEqual(response.status_code, 400)


class ListingSearchApiTests(FullTextAPITestCase):
    """
    Search through the API. TransactionTestCase is required for the same
    reason as in ListingSearchTests: the InnoDB FULLTEXT index is filled
    on commit.
    """

    def setUp(self):
        super().setUp()
        owner = make_user(group="landlords")
        make_listing(owner, title="Munich", city="München")
        make_listing(owner, title="Cologne", city="Köln")

    def titles(self, **params):
        response = self.client.get(LIST_URL, params)
        self.assertEqual(response.status_code, 200)
        return [item["title"] for item in response.json()["results"]]

    def test_search_filters_and_is_recorded(self):
        user = make_user()
        self.login(user)
        self.assertEqual(self.titles(search="Munich"), ["Munich"])
        query = SearchQuery.objects.get()
        self.assertEqual(query.keyword, "munich")
        self.assertEqual(query.results_count, 1)
        self.assertEqual(query.user, user)
