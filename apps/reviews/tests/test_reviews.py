from __future__ import annotations

from datetime import timedelta

from django.core.exceptions import ValidationError
from django.test import override_settings
from django.utils import timezone

from apps.bookings.models import BookingStatus
from apps.reviews.models import Review
from apps.reviews.selectors import owner_rating
from core.testing import (
    APITestCase, BaseTestCase, make_booking, make_completed_booking, make_listing, make_review,
    make_user,
)

LIST_URL = "/api/reviews/"


class ReviewModelTests(BaseTestCase):
    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        cls.owner = make_user()
        cls.tenant = make_user()
        cls.listing = make_listing(cls.owner)

    def test_listing_and_author_come_from_booking(self):
        review = make_review(make_completed_booking(self.listing, self.tenant))
        self.assertEqual(review.listing, self.listing)
        self.assertEqual(review.author, self.tenant)

    def test_only_completed_stays_can_be_reviewed(self):
        for status in (BookingStatus.PENDING, BookingStatus.CONFIRMED, BookingStatus.CANCELLED):
            booking = make_booking(self.listing, make_user(), start_offset=30, status=status)
            with self.subTest(status=status), self.assertRaises(ValidationError):
                make_review(booking)

    def test_rating_range(self):
        booking = make_completed_booking(self.listing, self.tenant)
        for rating in (0, 6):
            with self.subTest(rating=rating), self.assertRaises(ValidationError):
                make_review(booking, rating=rating)

    @override_settings(REVIEW_EDIT_WINDOW_DAYS=14)
    def test_edit_window(self):
        review = make_review(make_completed_booking(self.listing, self.tenant))
        self.assertTrue(review.is_editable)
        review.created_at = timezone.now() - timedelta(days=15)
        self.assertFalse(review.is_editable)

    def test_soft_delete_hides_review(self):
        review = make_review(make_completed_booking(self.listing, self.tenant))
        review.delete()
        self.assertFalse(Review.objects.filter(pk=review.pk).exists())
        self.assertTrue(Review.all_objects.filter(pk=review.pk).exists())

    def test_owner_rating_includes_deleted_listings_and_reviews(self):
        make_review(make_completed_booking(self.listing, self.tenant), rating=5)
        second_listing = make_listing(self.owner)
        review = make_review(make_completed_booking(second_listing, make_user()), rating=3)
        review.delete()
        second_listing.delete()
        self.assertEqual(owner_rating(self.owner), {"avg": 4.0, "total": 2})
        self.assertEqual(owner_rating(make_user()), {"avg": None, "total": 0})


class ReviewApiTests(APITestCase):
    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        cls.owner = make_user(group="landlords")
        cls.tenant = make_user(group="tenants")
        cls.listing = make_listing(cls.owner)

    def setUp(self):
        super().setUp()
        self.booking = make_completed_booking(self.listing, self.tenant)

    def create(self, user, booking=None, **extra):
        self.login(user)
        data = {"booking": str((booking or self.booking).public_id), "rating": 4, "text": "Nice"}
        data.update(extra)
        return self.client.post(LIST_URL, data, format="json")

    def test_tenant_reviews_completed_stay(self):
        response = self.create(self.tenant)
        self.assertEqual(response.status_code, 201)
        review = Review.objects.get()
        self.assertEqual(review.author, self.tenant)
        self.assertEqual(review.listing, self.listing)

    def test_anonymous_cannot_review(self):
        self.login(None)
        response = self.client.post(
            LIST_URL, {"booking": str(self.booking.public_id), "rating": 4}, format="json"
        )
        self.assertEqual(response.status_code, 401)

    def test_cannot_review_someone_elses_stay(self):
        self.assertEqual(self.create(make_user()).status_code, 400)

    def test_cannot_review_twice(self):
        self.create(self.tenant)
        self.assertEqual(self.create(self.tenant).status_code, 400)

    def test_cannot_review_unfinished_stay(self):
        upcoming = make_booking(self.listing, self.tenant, start_offset=10)
        self.assertEqual(self.create(self.tenant, booking=upcoming).status_code, 400)

    def test_invalid_rating_is_400(self):
        self.assertEqual(self.create(self.tenant, rating=9).status_code, 400)

    def test_list_and_retrieve_are_public(self):
        review = make_review(self.booking)
        self.assertEqual(self.client.get(LIST_URL).json()["count"], 1)
        body = self.client.get(f"{LIST_URL}{review.pk}/").json()
        self.assertEqual(body["author_email"], self.tenant.email)

    def test_author_edits_rating_and_text(self):
        review = make_review(self.booking, rating=2)
        self.login(self.tenant)
        response = self.client.patch(
            f"{LIST_URL}{review.pk}/", {"rating": 5, "text": "Better now"}, format="json"
        )
        self.assertEqual(response.status_code, 200)
        review.refresh_from_db()
        self.assertEqual((review.rating, review.text), (5, "Better now"))

    def test_put_with_same_booking_is_accepted(self):
        review = make_review(self.booking)
        self.login(self.tenant)
        response = self.client.put(
            f"{LIST_URL}{review.pk}/",
            {"booking": str(self.booking.public_id), "rating": 3, "text": "Ok"},
            format="json",
        )
        self.assertEqual(response.status_code, 200)

    def test_booking_cannot_be_moved_by_update(self):
        review = make_review(self.booking)
        other = make_completed_booking(self.listing, self.tenant, days_ago=30)
        self.login(self.tenant)
        self.client.patch(
            f"{LIST_URL}{review.pk}/", {"booking": str(other.public_id)}, format="json"
        )
        review.refresh_from_db()
        self.assertEqual(review.booking, self.booking)

    def test_other_user_cannot_edit(self):
        review = make_review(self.booking)
        self.login(self.owner)
        response = self.client.patch(f"{LIST_URL}{review.pk}/", {"rating": 1}, format="json")
        self.assertEqual(response.status_code, 403)

    def test_edit_window_expired(self):
        review = make_review(self.booking)
        Review.objects.filter(pk=review.pk).update(created_at=timezone.now() - timedelta(days=60))
        self.login(self.tenant)
        response = self.client.patch(f"{LIST_URL}{review.pk}/", {"rating": 1}, format="json")
        self.assertEqual(response.status_code, 403)

    def test_delete_is_not_available(self):
        review = make_review(self.booking)
        self.login(self.tenant)
        self.assertEqual(self.client.delete(f"{LIST_URL}{review.pk}/").status_code, 405)
