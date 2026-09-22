from __future__ import annotations

from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils.translation import gettext_lazy as _

from apps.listings.models import Listing
from decimal import ROUND_HALF_UP, Decimal
from .models import Booking, BookingStatus
import logging

logger = logging.getLogger(__name__)     # "apps.bookings.services"

@transaction.atomic
def create_booking(
        *, tenant, listing_id, start_date, end_date, guests=1,
        discount_percent=0) -> Booking:
    """
    Responsible for the transaction, the lock and freezing price and rate.
    The checks run in Booking.clean() via full_clean() inside the same
    critical section.
    """
    # the listing may have been deactivated or deleted after the serializer
    # validated it — report that as a 400 rather than a DoesNotExist 500
    listing = (
        Listing.objects.select_for_update()
        .filter(pk=listing_id, is_active=True)
        .first()
    )
    if listing is None:
        raise ValidationError(
            {"listing": _("This listing is not available for booking.")},
            code="listing_unavailable",
        )

    booking = Booking(
        listing=listing,
        tenant=tenant,
        start_date=start_date,
        end_date=end_date,
        guests=guests,
        discount_percent=discount_percent,
        status=BookingStatus.PENDING,
        price_per_night_snapshot=listing.price_per_night,
        listing_title_snapshot=listing.title,
    )
    booking.total_price = booking.calculate_total()

    # the rate at booking time and the amount computed with it.
    # Neither is ever recomputed.
    base_amount = Listing._to_base_currency(booking.total_price)
    booking.total_price_base = base_amount
    booking.exchange_rate = (
        base_amount / booking.total_price.amount
        if booking.total_price.amount
        else Decimal("1")
    ).quantize(Decimal("0.00000001"), rounding=ROUND_HALF_UP)

    booking.save()
    # INFO for successful business operations. The request_id is injected
    # automatically, so the line ties back to the HTTP request with no
    # manual plumbing.
    logger.info(
        "booking created id=%s listing=%s tenant=%s %s..%s total=%s %s",
        booking.pk, listing.pk, tenant.pk, start_date, end_date,
        # .amount is a Decimal with no locale formatting, currency separately
        booking.total_price.amount, booking.total_price.currency,
    )
    return booking


def change_status(booking: Booking, new_status: str) -> Booking:
    """
    Changes the status via save(): simple-history signals and the clean()
    transition check are both required. queryset.update() would skip both.
    """
    booking.status = new_status
    booking.save(update_fields=["status", "updated_at"])
    return booking