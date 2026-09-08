from __future__ import annotations

from datetime import date, timedelta

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import F, Q
from django.utils import timezone

from core.models import TimeStampedModel


class BookingStatus(models.TextChoices):
    """
    RU: Статусы жизненного цикла бронирования.
    EN: Booking lifecycle statuses.
    """

    PENDING = "pending", "Ожидает подтверждения"
    CONFIRMED = "confirmed", "Подтверждено"
    REJECTED = "rejected", "Отклонено"
    CANCELLED = "cancelled", "Отменено"
    COMPLETED = "completed", "Завершено"


# RU: статусы, при которых даты считаются занятыми.
# EN: statuses in which the dates are treated as occupied.
BLOCKING_STATUSES: tuple[str, ...] = (BookingStatus.PENDING, BookingStatus.CONFIRMED)

# RU: разрешённые переходы конечного автомата статусов.
# EN: allowed transitions of the status state machine.
STATUS_TRANSITIONS: dict[str, set[str]] = {
    BookingStatus.PENDING: {
        BookingStatus.CONFIRMED,
        BookingStatus.REJECTED,
        BookingStatus.CANCELLED,
    },
    BookingStatus.CONFIRMED: {BookingStatus.CANCELLED, BookingStatus.COMPLETED},
    BookingStatus.REJECTED: set(),
    BookingStatus.CANCELLED: set(),
    BookingStatus.COMPLETED: set(),
}


class BookingQuerySet(models.QuerySet):
    """
    RU: Переиспользуемые выборки бронирований.
    EN: Reusable booking queries.
    """

    def blocking(self) -> "BookingQuerySet":
        """
        RU: Брони, занимающие даты.
        EN: Bookings that occupy dates.
        """
        return self.filter(status__in=BLOCKING_STATUSES)

    def overlapping(self, listing, start_date: date, end_date: date) -> "BookingQuerySet":
        """
        RU: Пересекающиеся брони. Интервалы [a, b) и [c, d) пересекаются
            тогда и только тогда, когда a < d и c < b.
        EN: Overlapping bookings. Intervals [a, b) and [c, d) overlap
            if and only if a < d and c < b.
        """
        return self.blocking().filter(
            listing=listing,
            start_date__lt=end_date,
            end_date__gt=start_date,
        )

    def upcoming(self) -> "BookingQuerySet":
        """
        RU: Брони, не завершившиеся на сегодня.
        EN: Bookings that have not ended as of today.
        """
        return self.filter(end_date__gte=timezone.localdate())


class Booking(TimeStampedModel):
    """
    RU: Бронирование жилья на интервал [start_date, end_date),
        где день выезда не входит в занятый период.
    EN: A property booking over the interval [start_date, end_date),
        where the check-out day is not part of the occupied period.
    """

    # RU: PROTECT — страховка от физического удаления объявления с бронями.
    # EN: PROTECT guards against physically deleting a listing that has bookings.
    listing = models.ForeignKey(
        "listings.Listing",
        on_delete=models.PROTECT,
        related_name="bookings",
    )
    tenant = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="bookings",
    )

    start_date = models.DateField()
    end_date = models.DateField()
    guests = models.PositiveSmallIntegerField(default=1)

    status = models.CharField(
        max_length=16,
        choices=BookingStatus.choices,
        default=BookingStatus.PENDING,
        db_index=True,
    )

    # RU: снимки на момент бронирования — цена объявления и его заголовок
    #     могут измениться или объявление может быть удалено.
    # EN: snapshots taken at booking time — the listing price and title
    #     may change, or the listing may be removed altogether.
    price_per_night_snapshot = models.DecimalField(max_digits=10, decimal_places=2)
    total_price = models.DecimalField(max_digits=12, decimal_places=2)
    listing_title_snapshot = models.CharField(max_length=200)

    confirmed_at = models.DateTimeField(null=True, blank=True, editable=False)
    cancelled_at = models.DateTimeField(null=True, blank=True, editable=False)

    objects = BookingQuerySet.as_manager()

    class Meta:
        verbose_name = "Бронирование"
        verbose_name_plural = "Бронирования"
        ordering = ("-created_at", "-id")
        constraints = [
            models.CheckConstraint(
                condition=Q(end_date__gt=F("start_date")),
                name="booking_end_after_start",
            ),
            models.CheckConstraint(
                condition=Q(total_price__gte=0), name="booking_total_price_gte_zero"
            ),
        ]
        indexes = [
            models.Index(
                fields=("listing", "start_date", "end_date"),
                name="booking_listing_dates_idx",
            ),
            models.Index(fields=("tenant", "status"), name="booking_tenant_status_idx"),
        ]

    def __str__(self) -> str:
        return f"{self.listing_title_snapshot}: {self.start_date}–{self.end_date}"

    @property
    def nights(self) -> int:
        """
        RU: Количество оплачиваемых ночей.
        EN: Number of chargeable nights.
        """
        return (self.end_date - self.start_date).days

    def can_transition_to(self, new_status: str) -> bool:
        """
        RU: Допустим ли переход в указанный статус.
        EN: Whether a transition to the given status is allowed.
        """
        return new_status in STATUS_TRANSITIONS[self.status]

    def is_cancellable(self) -> bool:
        """
        RU: Не истёк ли срок бесплатной отмены. Порог берётся из настроек,
            чтобы правило не было зашито в код.
        EN: Whether the cancellation deadline has not passed. The threshold comes
            from settings so the rule is not hard-coded.
        """
        deadline = self.start_date - timedelta(
            days=getattr(settings, "BOOKING_CANCELLATION_DAYS", 1)
        )
        return self.status in BLOCKING_STATUSES and timezone.localdate() <= deadline

    def clean(self) -> None:
        """
        RU: Правила, невыразимые CHECK-ограничением: «сегодня» недетерминировано,
            а пересечение требует запроса к другим строкам.
        EN: Rules a CHECK constraint cannot express: "today" is non-deterministic,
            and overlap detection requires querying other rows.
        """
        errors: dict[str, str] = {}
        if self.start_date and self.start_date < timezone.localdate():
            errors["start_date"] = "Нельзя бронировать в прошлом."
        if self.start_date and self.end_date and self.end_date <= self.start_date:
            errors["end_date"] = "Дата выезда должна быть позже даты заезда."
        if self.listing_id and self.start_date and self.end_date:
            conflicts = Booking.objects.overlapping(
                self.listing, self.start_date, self.end_date
            ).exclude(pk=self.pk)
            if conflicts.exists():
                errors["__all__"] = "Эти даты уже заняты."
        if errors:
            raise ValidationError(errors)