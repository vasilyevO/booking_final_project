# apps/bookings/management/commands/complete_bookings.py
from django.core.management.base import BaseCommand
from django.utils import timezone

from apps.bookings.models import Booking, BookingStatus


class Command(BaseCommand):
    """
    RU: Переводит подтверждённые брони в COMPLETED после даты выезда.
        Завершение — функция времени, а не чьё-то действие, поэтому его
        не делает ни арендатор, ни владелец.
    EN: Moves confirmed bookings to COMPLETED once the check-out date has
        passed. Completion is a function of time rather than anyone's action,
        so neither the tenant nor the landlord performs it.
    """

    help = "Mark confirmed bookings as completed after check-out"

    def handle(self, *args, **options) -> None:
        today = timezone.localdate()
        # RU: цикл с save(), а не update(): нужны сигналы simple-history
        # EN: a save() loop rather than update(): simple-history needs signals
        count = 0
        for booking in Booking.objects.filter(
            status=BookingStatus.CONFIRMED, end_date__lte=today
        ):
            booking.status = BookingStatus.COMPLETED
            booking.save(update_fields=["status", "updated_at"])
            count += 1
        self.stdout.write(self.style.SUCCESS(f"completed: {count}"))