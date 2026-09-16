from __future__ import annotations

from datetime import date

from django.db import transaction
from apps.listings.models import Listing
from decimal import ROUND_HALF_UP, Decimal
from .models import Booking, BookingStatus


@transaction.atomic
def create_booking(
    *, tenant, listing_id: int, start_date: date, end_date: date,
    guests: int = 1, discount_percent: int = 0,
) -> Booking:
    """
    RU: Отвечает за транзакцию, блокировку и заморозку цены с курсом.
        Проверки выполняет Booking.clean() через full_clean() внутри
        той же критической секции.
    EN: Responsible for the transaction, the lock and freezing price and rate.
        The checks run in Booking.clean() via full_clean() inside the same
        critical section.
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
    booking.total_price = booking.calculate_total()

    # RU: курс на момент бронирования и сумма по нему. Пересчёту не подлежат.
    # EN: the rate at booking time and the amount computed with it.
    #     Neither is ever recomputed.
    base_amount = Listing._to_base_currency(booking.total_price)
    booking.total_price_base = base_amount
    booking.exchange_rate = (
        base_amount / booking.total_price.amount
        if booking.total_price.amount
        else Decimal("1")
    ).quantize(Decimal("0.00000001"), rounding=ROUND_HALF_UP)

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