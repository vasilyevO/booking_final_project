from __future__ import annotations

from io import StringIO

from django.core.management import call_command
from django.core.management.base import CommandError

from apps.analytics.models import ListingStats
from apps.bookings.models import Booking, BookingStatus
from apps.listings.management.commands.seed_demo import DEMO_DOMAIN
from apps.listings.models import Listing
from apps.reviews.models import Review
from apps.users.models import User
from core.testing import BaseTestCase, make_user


class SeedDemoCommandTests(BaseTestCase):
    def seed(self, *args):
        out = StringIO()
        call_command(
            "seed_demo", "--landlords", "2", "--tenants", "4", "--listings", "5",
            "--no-photos", *args, stdout=out,
        )
        return out.getvalue()

    def test_creates_consistent_dataset(self):
        output = self.seed()
        self.assertIn("demo data ready", output)

        demo_users = User.objects.filter(email__endswith=f"@{DEMO_DOMAIN}")
        self.assertEqual(demo_users.count(), 6)
        self.assertEqual(Listing.all_objects.count(), 5)
        self.assertTrue(Booking.objects.exists())
        self.assertTrue(ListingStats.objects.exists())

        for review in Review.all_objects.select_related("booking"):
            self.assertEqual(review.booking.status, BookingStatus.COMPLETED)
        for booking in Booking.objects.select_related("listing"):
            self.assertNotEqual(booking.tenant_id, booking.listing.owner_id)

    def test_same_seed_is_reproducible(self):
        self.seed("--seed", "7")
        first = sorted(Listing.all_objects.values_list("title", flat=True))
        self.seed("--flush", "--seed", "7")
        second = sorted(Listing.all_objects.values_list("title", flat=True))
        self.assertEqual(first, second)

    def test_flush_removes_demo_data_only(self):
        real_user = make_user(email="real@example.com")
        self.seed()
        self.seed("--flush", "--listings", "0", "--landlords", "1", "--tenants", "1")

        self.assertTrue(User.objects.filter(pk=real_user.pk).exists())
        self.assertEqual(Listing.all_objects.count(), 0)
        self.assertEqual(Listing.history.count(), 0)
        self.assertEqual(Booking.history.count(), 0)

    def test_rejects_unknown_language(self):
        with self.assertRaises(CommandError):
            self.seed("--languages", "en,xx")
