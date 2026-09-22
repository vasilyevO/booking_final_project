from __future__ import annotations

from datetime import timedelta
from decimal import Decimal
from io import StringIO

from django.core.exceptions import ValidationError
from django.core.management import call_command
from django.test import override_settings
from djmoney.money import Money

from apps.bookings.models import STATUS_TRANSITIONS, Booking, BookingStatus
from apps.bookings.services import change_status, create_booking
from core.testing import BaseTestCase, make_booking, make_listing, make_user, today


class BookingModelTests(BaseTestCase):
    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        cls.owner = make_user()
        cls.tenant = make_user()
        cls.listing = make_listing(cls.owner, price_per_night=Money("100.00", "EUR"))

    def test_nights_and_str(self):
        booking = make_booking(self.listing, self.tenant, start_offset=10, nights=4)
        self.assertEqual(booking.nights, 4)
        self.assertIn(self.listing.title, str(booking))

    def test_calculate_total_with_discount_is_rounded(self):
        booking = Booking(
            price_per_night_snapshot=Money("33.33", "EUR"),
            start_date=today(), end_date=today() + timedelta(days=3),
            discount_percent=15,
        )
        # 99.99 * 0.85 = 84.9915
        self.assertEqual(booking.calculate_total(), Money("84.99", "EUR"))

    def test_state_machine(self):
        booking = make_booking(self.listing, self.tenant)
        for target in BookingStatus.values:
            with self.subTest(target=target):
                self.assertEqual(
                    booking.can_transition_to(target),
                    target in STATUS_TRANSITIONS[BookingStatus.PENDING],
                )

    def test_start_in_the_past_is_rejected(self):
        booking = Booking(
            listing=self.listing, tenant=self.tenant,
            start_date=today() - timedelta(days=1), end_date=today() + timedelta(days=1),
            price_per_night_snapshot=Money("100", "EUR"), total_price=Money("200", "EUR"),
        )
        with self.assertRaises(ValidationError) as ctx:
            booking.save()
        self.assertIn("start_date", ctx.exception.message_dict)

    def test_end_must_be_after_start(self):
        with self.assertRaises(ValidationError):
            make_booking(self.listing, self.tenant, nights=0)

    def test_owner_cannot_book_own_listing(self):
        with self.assertRaises(ValidationError) as ctx:
            make_booking(self.listing, self.owner)
        self.assertIn("tenant", ctx.exception.message_dict)

    def test_guests_range(self):
        booking = make_booking(self.listing, self.tenant)
        for guests in (0, 21):
            booking.guests = guests
            with self.subTest(guests=guests), self.assertRaises(ValidationError):
                booking.save()

    def test_overlapping_dates_are_rejected(self):
        make_booking(self.listing, self.tenant, start_offset=10, nights=5)
        with self.assertRaises(ValidationError) as ctx:
            make_booking(self.listing, make_user(), start_offset=12, nights=5)
        self.assertEqual(ctx.exception.error_dict["__all__"][0].code, "dates_taken")

    def test_back_to_back_bookings_are_allowed(self):
        make_booking(self.listing, self.tenant, start_offset=10, nights=5)
        # check-out day of the first stay is the check-in day of the next
        make_booking(self.listing, make_user(), start_offset=15, nights=2)
        make_booking(self.listing, make_user(), start_offset=8, nights=2)

    def test_cancelled_bookings_do_not_block_dates(self):
        first = make_booking(self.listing, self.tenant, start_offset=10, nights=5)
        change_status(first, BookingStatus.CANCELLED)
        make_booking(self.listing, make_user(), start_offset=10, nights=5)

    def test_invalid_transition_is_rejected(self):
        booking = make_booking(self.listing, self.tenant)
        change_status(booking, BookingStatus.REJECTED)
        with self.assertRaises(ValidationError) as ctx:
            change_status(booking, BookingStatus.CONFIRMED)
        self.assertEqual(ctx.exception.error_dict["status"][0].code, "invalid_transition")

    def test_cannot_complete_before_checkout(self):
        booking = make_booking(self.listing, self.tenant, status=BookingStatus.CONFIRMED)
        with self.assertRaises(ValidationError) as ctx:
            change_status(booking, BookingStatus.COMPLETED)
        self.assertEqual(ctx.exception.error_dict["status"][0].code, "completed_too_early")

    def test_status_loaded_from_db_is_tracked(self):
        booking = make_booking(self.listing, self.tenant)
        loaded = Booking.objects.get(pk=booking.pk)
        self.assertEqual(loaded._original_status, BookingStatus.PENDING)
        loaded.status = BookingStatus.COMPLETED
        with self.assertRaises(ValidationError):
            loaded.save()

    def test_status_change_is_recorded_in_history(self):
        booking = make_booking(self.listing, self.tenant)
        change_status(booking, BookingStatus.CONFIRMED)
        self.assertEqual(
            list(booking.history.values_list("status", flat=True)),
            [BookingStatus.CONFIRMED, BookingStatus.PENDING],
        )

    @override_settings(BOOKING_CANCELLATION_DAYS=3)
    def test_is_cancellable_respects_deadline(self):
        self.assertTrue(make_booking(self.listing, self.tenant, start_offset=3).is_cancellable())
        late = make_booking(self.listing, make_user(), start_offset=2, nights=1)
        self.assertFalse(late.is_cancellable())

    def test_finished_statuses_are_not_cancellable(self):
        booking = make_booking(self.listing, self.tenant, start_offset=10)
        change_status(booking, BookingStatus.REJECTED)
        self.assertFalse(booking.is_cancellable())

    def test_queryset_helpers(self):
        upcoming = make_booking(self.listing, self.tenant, start_offset=10)
        past = make_booking(
            self.listing, self.tenant, start_offset=-10, nights=2, status=BookingStatus.COMPLETED
        )
        self.assertIn(upcoming, Booking.objects.upcoming())
        self.assertNotIn(past, Booking.objects.upcoming())
        self.assertEqual(list(Booking.objects.blocking()), [upcoming])


class CreateBookingServiceTests(BaseTestCase):
    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        cls.owner = make_user()
        cls.tenant = make_user()

    def book(self, listing, **extra):
        data = {
            "tenant": self.tenant,
            "listing_id": listing.pk,
            "start_date": today() + timedelta(days=5),
            "end_date": today() + timedelta(days=8),
        }
        data.update(extra)
        return create_booking(**data)

    def test_snapshots_are_frozen(self):
        listing = make_listing(self.owner, title="Original", price_per_night=Money("80", "EUR"))
        booking = self.book(listing, guests=2, discount_percent=10)
        listing.title = "Renamed"
        listing.price_per_night = Money("500", "EUR")
        listing.save()
        booking.refresh_from_db()
        self.assertEqual(booking.status, BookingStatus.PENDING)
        self.assertEqual(booking.listing_title_snapshot, "Original")
        self.assertEqual(booking.price_per_night_snapshot, Money("80", "EUR"))
        self.assertEqual(booking.total_price, Money("216.00", "EUR"))
        self.assertEqual(booking.total_price_base, Decimal("216.00"))
        self.assertEqual(booking.exchange_rate, Decimal("1"))

    def test_exchange_rate_is_frozen_for_foreign_currency(self):
        listing = make_listing(self.owner, price_per_night=Money("109", "USD"))
        booking = self.book(listing)
        self.assertEqual(booking.total_price, Money("327.00", "USD"))
        self.assertEqual(booking.total_price_base, Decimal("300.00"))
        self.assertEqual(booking.exchange_rate, Decimal("0.91743119"))

    def test_inactive_listing_is_rejected(self):
        listing = make_listing(self.owner, is_active=False)
        with self.assertRaises(ValidationError) as ctx:
            self.book(listing)
        self.assertIn("listing", ctx.exception.message_dict)

    def test_failed_validation_leaves_no_row(self):
        listing = make_listing(self.owner)
        with self.assertRaises(ValidationError):
            self.book(listing, tenant=self.owner)
        self.assertFalse(Booking.objects.exists())


class CompleteBookingsCommandTests(BaseTestCase):
    def test_completes_confirmed_bookings_after_checkout(self):
        listing = make_listing(make_user())
        tenant = make_user()
        finished = make_booking(
            listing, tenant, start_offset=-5, nights=3, status=BookingStatus.CONFIRMED
        )
        ongoing = make_booking(
            listing, tenant, start_offset=-1, nights=3, status=BookingStatus.CONFIRMED
        )
        pending_past = make_booking(listing, tenant, start_offset=-10, nights=2)

        out = StringIO()
        call_command("complete_bookings", stdout=out)

        self.assertIn("completed: 1", out.getvalue())
        for booking, expected in (
            (finished, BookingStatus.COMPLETED),
            (ongoing, BookingStatus.CONFIRMED),
            (pending_past, BookingStatus.PENDING),
        ):
            booking.refresh_from_db()
            self.assertEqual(booking.status, expected)
        self.assertEqual(finished.history.count(), 2)
