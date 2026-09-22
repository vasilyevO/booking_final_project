from __future__ import annotations

import logging
from types import SimpleNamespace

from django.core.exceptions import ValidationError
from django.test import SimpleTestCase, override_settings
from rest_framework.test import APIClient

from apps.listings.models import Listing
from core.logging_context import (
    RequestIdFilter, get_request_id, new_request_id, reset_request_id, set_request_id,
)
from core.pagination import DefaultPagination
from core.permissions import (
    IsBookingParticipant, IsListingOwner, IsOwnerOrReadOnly, IsReviewAuthor,
)
from core.testing import (
    BaseTestCase, make_booking, make_completed_booking, make_listing, make_review, make_user,
)
from core.text import normalize_search_text, spelling_variants
from core.validators import validate_not_own_listing


class NormalizeSearchTextTests(SimpleTestCase):
    def test_folds_umlauts_and_case(self):
        for spelling in ("Köln", "Koeln", "KÖLN", "  köln  "):
            self.assertEqual(normalize_search_text(spelling), "koeln")

    def test_folds_sharp_s_and_accents(self):
        self.assertEqual(normalize_search_text("Straße"), "strasse")
        self.assertEqual(normalize_search_text("Café"), "cafe")

    def test_empty_values(self):
        self.assertEqual(normalize_search_text(""), "")
        self.assertEqual(normalize_search_text(None), "")


class SpellingVariantsTests(SimpleTestCase):
    def test_umlaut_without_diacritic_matches_spelled_out_form(self):
        self.assertEqual(spelling_variants("koln"), {"koln", "koeln"})
        self.assertEqual(spelling_variants("Munchen"), {"munchen", "muenchen"})

    def test_spelled_out_umlaut_is_not_expanded_again(self):
        self.assertEqual(spelling_variants("Koeln"), {"koeln"})
        self.assertEqual(spelling_variants("Köln"), {"koeln"})

    def test_variant_count_is_capped(self):
        self.assertEqual(len(spelling_variants("aoaoaoaoaoao")), 64)

    def test_empty(self):
        self.assertEqual(spelling_variants(" "), set())


class RequestIdTests(SimpleTestCase):
    def test_default_outside_request(self):
        self.assertEqual(get_request_id(), "-")

    def test_set_and_reset(self):
        token = set_request_id("abc")
        try:
            self.assertEqual(get_request_id(), "abc")
        finally:
            reset_request_id(token)
        self.assertEqual(get_request_id(), "-")

    def test_new_request_id_is_short_hex(self):
        value = new_request_id()
        self.assertEqual(len(value), 12)
        int(value, 16)

    def test_filter_injects_request_id(self):
        record = logging.LogRecord("x", logging.INFO, __file__, 1, "msg", (), None)
        token = set_request_id("req-1")
        try:
            self.assertTrue(RequestIdFilter().filter(record))
        finally:
            reset_request_id(token)
        self.assertEqual(record.request_id, "req-1")


class PaginationTests(SimpleTestCase):
    def test_page_size_is_capped(self):
        paginator = DefaultPagination()
        request = SimpleNamespace(query_params={"page_size": "10000"})
        self.assertEqual(paginator.get_page_size(request), 100)


def _request(method: str, user):
    return SimpleNamespace(method=method, user=user)


class PermissionTests(BaseTestCase):
    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        cls.owner = make_user(group="landlords")
        cls.tenant = make_user(group="tenants")
        cls.stranger = make_user(group="tenants")
        cls.staff = make_user(is_staff=True)
        cls.listing = make_listing(cls.owner)
        cls.booking = make_booking(cls.listing, cls.tenant)

    def test_owner_or_read_only(self):
        perm = IsOwnerOrReadOnly()
        self.assertTrue(perm.has_object_permission(_request("GET", self.stranger), None, self.listing))
        self.assertTrue(perm.has_object_permission(_request("PATCH", self.owner), None, self.listing))
        self.assertTrue(perm.has_object_permission(_request("PATCH", self.staff), None, self.listing))
        self.assertFalse(perm.has_object_permission(_request("PATCH", self.stranger), None, self.listing))

    def test_booking_participant(self):
        perm = IsBookingParticipant()
        for user, expected in (
            (self.tenant, True), (self.owner, True), (self.staff, True), (self.stranger, False),
        ):
            with self.subTest(user=user.email):
                self.assertEqual(
                    perm.has_object_permission(_request("GET", user), None, self.booking), expected
                )

    def test_listing_owner(self):
        perm = IsListingOwner()
        self.assertTrue(perm.has_object_permission(_request("POST", self.owner), None, self.booking))
        self.assertFalse(perm.has_object_permission(_request("POST", self.tenant), None, self.booking))

    def test_review_author(self):
        booking = make_completed_booking(self.listing, self.stranger)
        review = make_review(booking)
        perm = IsReviewAuthor()
        self.assertTrue(perm.has_object_permission(_request("GET", self.tenant), None, review))
        self.assertTrue(perm.has_object_permission(_request("PATCH", self.stranger), None, review))
        self.assertFalse(perm.has_object_permission(_request("PATCH", self.tenant), None, review))
        # nobody but staff may delete, not even the author
        self.assertFalse(perm.has_object_permission(_request("DELETE", self.stranger), None, review))
        self.assertTrue(perm.has_object_permission(_request("DELETE", self.staff), None, review))


class ValidateNotOwnListingTests(BaseTestCase):
    def test_rejects_owner(self):
        owner = make_user()
        listing = make_listing(owner)
        with self.assertRaises(ValidationError) as ctx:
            validate_not_own_listing(listing, owner)
        self.assertEqual(ctx.exception.code, "own_listing")

    def test_allows_other_user_and_missing_values(self):
        listing = make_listing(make_user())
        validate_not_own_listing(listing, make_user())
        validate_not_own_listing(None, None)


class SoftDeleteTests(BaseTestCase):
    def setUp(self):
        self.listing = make_listing(make_user())

    def test_delete_marks_row(self):
        self.listing.delete()
        self.assertTrue(self.listing.is_deleted)
        self.assertFalse(Listing.objects.filter(pk=self.listing.pk).exists())
        self.assertTrue(Listing.all_objects.filter(pk=self.listing.pk).exists())

    def test_restore(self):
        self.listing.delete()
        self.listing.restore()
        self.assertFalse(self.listing.is_deleted)
        self.assertTrue(Listing.objects.filter(pk=self.listing.pk).exists())

    def test_delete_is_recorded_in_history(self):
        self.listing.delete()
        self.assertIsNotNone(self.listing.history.first().deleted_at)

    def test_related_object_resolves_after_soft_delete(self):
        booking = make_booking(self.listing, make_user())
        self.listing.delete()
        booking.refresh_from_db()
        self.assertEqual(booking.listing.pk, self.listing.pk)


class ValidatedModelTests(BaseTestCase):
    def test_save_runs_full_clean(self):
        with self.assertRaises(ValidationError) as ctx:
            make_listing(make_user(), rooms=0)
        self.assertIn("rooms", ctx.exception.message_dict)

    def test_skip_validation_bypasses_clean(self):
        listing = make_listing(make_user())
        listing.rooms = 60
        listing.save(skip_validation=True)
        listing.refresh_from_db()
        self.assertEqual(listing.rooms, 60)

    def test_partial_save_validates_only_written_fields(self):
        listing = make_listing(make_user())
        listing.rooms = 0  # invalid, but neither validated nor written
        listing.title = "New title"
        listing.save(update_fields=["title"])
        listing.refresh_from_db()
        self.assertEqual(listing.title, "New title")
        self.assertEqual(listing.rooms, 2)


class DbSignalLoggingTests(BaseTestCase):
    def test_create_update_and_delete_are_logged(self):
        with self.assertLogs("core.db", level="INFO") as logs:
            listing = make_listing(make_user())
            listing.title = "Changed"
            listing.save(update_fields=["title"])
        output = "\n".join(logs.output)
        self.assertIn(f"create listings.Listing pk={listing.pk}", output)
        self.assertIn(f"update listings.Listing pk={listing.pk}", output)
        self.assertNotIn("Historical", output)

    def test_physical_delete_is_logged_as_warning(self):
        user = make_user()
        pk = user.pk
        with self.assertLogs("core.db", level="WARNING") as logs:
            user.delete()
        self.assertIn(f"delete users.User pk={pk}", logs.output[0])


class RequestMiddlewareTests(BaseTestCase):
    def test_generates_and_returns_request_id(self):
        response = APIClient().get("/api/listings/")
        self.assertEqual(len(response["X-Request-ID"]), 12)

    def test_honours_incoming_request_id(self):
        response = APIClient().get("/api/listings/", HTTP_X_REQUEST_ID="trace-42")
        self.assertEqual(response["X-Request-ID"], "trace-42")

    def test_error_responses_are_logged_as_warning(self):
        with self.assertLogs("core.request", level="WARNING") as logs:
            APIClient().get("/api/bookings/")
        self.assertIn("GET /api/bookings/ -> 401", logs.output[0])

    @override_settings(DEBUG=True, QUERY_COUNT_WARNING=0)
    def test_query_count_warning(self):
        with self.assertLogs("core.queries", level="WARNING") as logs:
            APIClient().get("/api/listings/")
        self.assertIn("possible N+1", logs.output[0])


class ExceptionHandlerTests(BaseTestCase):
    def test_model_validation_error_becomes_400(self):
        owner = make_user(group="tenants")
        listing = make_listing(owner)
        client = APIClient()
        client.force_authenticate(owner)
        response = client.post("/api/bookings/", {
            "listing": str(listing.public_id),
            "start_date": "2999-01-01",
            "end_date": "2999-01-03",
        }, format="json")
        self.assertEqual(response.status_code, 400)
        body = response.json()
        self.assertEqual(body["type"], "validation_error")
        self.assertIn("tenant", {error["attr"] for error in body["errors"]})


class SchemaTests(BaseTestCase):
    def test_openapi_schema_is_generated(self):
        response = APIClient().get("/api/schema/")
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"/api/bookings/", response.content)

