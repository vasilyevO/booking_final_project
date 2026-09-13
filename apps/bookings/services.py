from __future__ import annotations

from datetime import date

from django.db import transaction
from apps.listings.models import Listing
from .models import Booking, BookingStatus


@transaction.atomic
def create_booking(
    *, tenant, listing_id: int, start_date, end_date,
    guests: int = 1, discount_percent: int = 0,
) -> Booking:
    """
    RU: Отвечает только за транзакцию и блокировку. Проверки «не своё жильё»
        и «даты свободны» выполняет Booking.clean() через full_clean()
        внутри той же критической секции — дублировать их здесь незачем.
    EN: Responsible only for the transaction and the lock. The "not your own
        listing" and "dates are free" checks run in Booking.clean() via
        full_clean() inside the same critical section — no need to repeat them.
    """
    listing = Listing.objects.select_for_update().get(pk=listing_id, is_active=True)

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
    # RU: сумма считается методом модели — формула живёт в одном месте
    # EN: the total comes from a model method — the formula lives in one place
    booking.total_price = booking.calculate_total()
    booking.save()
    return booking


def change_status(booking: Booking, new_status: str) -> Booking:
    """
    RU: Меняет статус через save(): нужны сигналы simple-history и проверка
        перехода в clean(). queryset.update() обошёл бы оба.
    EN: Changes the status via save(): simple-history signals and the clean()
        transition check are both required. queryset.update() would skip both.
    """
    booking.status = new_status
    booking.save(update_fields=["status", "updated_at"])
    return booking