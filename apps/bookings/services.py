# apps/bookings/services.py
from __future__ import annotations

from datetime import date

from django.db import transaction

from apps.listings.models import Listing
from .models import Booking, BookingStatus


@transaction.atomic
def create_booking(
    *,
    tenant,
    listing_id: int,
    start_date: date,
    end_date: date,
    guests: int = 1,
) -> Booking:
    """
    RU: Создаёт бронирование атомарно, исключая гонку двух параллельных запросов
        на одни и те же даты.
    EN: Creates a booking atomically, preventing a race between two concurrent
        requests for the same dates.
    """
    # RU: select_for_update блокирует строку объявления до конца транзакции.
    # EN: select_for_update locks the listing row until the transaction ends.
    listing = Listing.objects.select_for_update().get(pk=listing_id, is_active=True)

    if Booking.objects.overlapping(listing, start_date, end_date).exists():
        raise ValueError("Dates are already taken")

    nights = (end_date - start_date).days
    return Booking.objects.create(
        listing=listing,
        tenant=tenant,
        start_date=start_date,
        end_date=end_date,
        guests=guests,
        status=BookingStatus.PENDING,
        price_per_night_snapshot=listing.price_per_night,
        total_price=listing.price_per_night * nights,
        listing_title_snapshot=listing.title,
    )