from __future__ import annotations

from datetime import date

from django.core.exceptions import ValidationError
from django.db import transaction

from apps.listings.models import Listing
from core.validators import validate_not_own_listing
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

    validate_not_own_listing(listing, tenant)

    if Booking.objects.overlapping(listing, start_date, end_date).exists():
        raise ValidationError("Эти даты уже заняты.")

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


def change_status(booking: Booking, new_status: str) -> Booking:
    """
    RU: Меняет статус через save(), а не queryset.update() — иначе изменение
        не попадёт ни в историю, ни в updated_at.
    EN: Changes the status via save() rather than queryset.update() — otherwise
        the change would reach neither the history nor updated_at.
    """
    if not booking.can_transition_to(new_status):
        raise ValidationError(f"Переход {booking.status} → {new_status} недопустим.")
    booking.status = new_status
    booking.save(update_fields=["status", "updated_at"])
    return booking