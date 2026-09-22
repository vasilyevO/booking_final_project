from __future__ import annotations

from datetime import timedelta
from pathlib import Path
from unittest import mock, skipUnless

from django.conf import settings
from django.core import mail
from django.db import transaction

from apps.bookings.models import BookingStatus
from apps.bookings.notifications import send_booking_created_emails, send_booking_status_email
from apps.bookings.services import change_status, create_booking
from core.testing import BaseTestCase, make_booking, make_listing, make_user, today

GERMAN_CATALOG = Path(settings.BASE_DIR) / "locale" / "de" / "LC_MESSAGES" / "django.mo"


class BookingEmailTests(BaseTestCase):
    """
    on_commit callbacks never fire inside a TestCase: every test runs in a
    transaction that is rolled back. captureOnCommitCallbacks(execute=True)
    runs them explicitly.
    """

    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        cls.owner = make_user(email="owner@example.com", language="de")
        cls.tenant = make_user(email="tenant@example.com", language="en")
        cls.listing = make_listing(cls.owner, title="River flat")

    def create(self):
        return create_booking(
            tenant=self.tenant,
            listing_id=self.listing.pk,
            start_date=today() + timedelta(days=3),
            end_date=today() + timedelta(days=5),
        )

    def test_creation_emails_both_parties(self):
        with self.captureOnCommitCallbacks(execute=True):
            booking = self.create()

        self.assertEqual(len(mail.outbox), 2)
        tenant_mail, owner_mail = mail.outbox
        self.assertEqual(tenant_mail.to, [self.tenant.email])
        self.assertEqual(owner_mail.to, [self.owner.email])
        self.assertEqual(tenant_mail.subject, "Your booking request has been created")
        self.assertIn("River flat", tenant_mail.body)
        self.assertIn(str(booking.public_id), owner_mail.body)

    @skipUnless(GERMAN_CATALOG.exists(), "compiled translations are required (compilemessages)")
    def test_each_email_uses_recipient_language(self):
        with self.captureOnCommitCallbacks(execute=True):
            self.create()
        self.assertEqual(mail.outbox[1].subject, "Neue Buchungsanfrage für Ihre Unterkunft")

    def test_no_email_before_commit(self):
        with self.captureOnCommitCallbacks(execute=False) as callbacks:
            self.create()
        self.assertEqual(len(callbacks), 1)
        self.assertEqual(mail.outbox, [])

    def test_no_email_when_transaction_rolls_back(self):
        with self.captureOnCommitCallbacks(execute=True):
            try:
                with transaction.atomic():
                    self.create()
                    raise RuntimeError("abort")
            except RuntimeError:
                pass
        self.assertEqual(mail.outbox, [])

    def test_status_change_emails_tenant(self):
        booking = make_booking(self.listing, self.tenant)
        with self.captureOnCommitCallbacks(execute=True):
            change_status(booking, BookingStatus.CONFIRMED)
        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(mail.outbox[0].to, [self.tenant.email])
        self.assertEqual(mail.outbox[0].subject, "Your booking has been confirmed")
        self.assertIn("Confirmed", mail.outbox[0].body)

    def test_saving_without_status_change_sends_nothing(self):
        booking = make_booking(self.listing, self.tenant)
        with self.captureOnCommitCallbacks(execute=True):
            booking.guests = 2
            booking.save()
        self.assertEqual(mail.outbox, [])

    def test_send_failure_is_logged_not_raised(self):
        booking = make_booking(self.listing, self.tenant)
        with mock.patch(
            "apps.bookings.notifications.send_mail", side_effect=OSError("smtp down")
        ), self.assertLogs("apps.bookings.notifications", level="ERROR") as logs:
            send_booking_created_emails(booking.pk)
        self.assertEqual(len(logs.output), 2)

    def test_missing_booking_is_ignored(self):
        send_booking_created_emails(999_999)
        send_booking_status_email(999_999, BookingStatus.PENDING)
        self.assertEqual(mail.outbox, [])

    def test_pending_status_has_no_email(self):
        booking = make_booking(self.listing, self.tenant)
        send_booking_status_email(booking.pk, BookingStatus.PENDING)
        self.assertEqual(mail.outbox, [])
