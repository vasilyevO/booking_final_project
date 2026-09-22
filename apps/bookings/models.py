from __future__ import annotations

from datetime import date, timedelta

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models
from django.db.models import F, Q
from django.utils import timezone
from djmoney.models.fields import MoneyField
from djmoney.money import Money
from simple_history.models import HistoricalRecords
from decimal import ROUND_HALF_UP, Decimal
from django.utils.translation import gettext_lazy as _

from core.models import PublicIdModel, TimeStampedModel, ValidatedModel
from core.validators import validate_not_own_listing


class BookingStatus(models.TextChoices):
    """
    Booking lifecycle statuses.
    """

    PENDING = "pending", _("Pending")
    CONFIRMED = "confirmed", _("Confirmed")
    REJECTED = "rejected", _("Rejected")
    CANCELLED = "cancelled", _("Cancelled")
    COMPLETED = "completed", _("Completed")


# statuses in which the dates are treated as occupied.
BLOCKING_STATUSES: tuple[str, ...] = (BookingStatus.PENDING, BookingStatus.CONFIRMED)

# allowed transitions of the status state machine.
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
    Reusable booking queries.
    """

    def blocking(self) -> "BookingQuerySet":
        """
        Bookings that occupy dates.
        """
        return self.filter(status__in=BLOCKING_STATUSES)

    def overlapping(self, listing, start_date: date, end_date: date) -> "BookingQuerySet":
        """
        Overlapping bookings. Intervals [a, b) and [c, d) overlap
        if and only if a < d and c < b.
        """
        return self.blocking().filter(
            listing=listing,
            start_date__lt=end_date,
            end_date__gt=start_date,
        )

    def upcoming(self) -> "BookingQuerySet":
        """
        Bookings that have not ended as of today.
        """
        return self.filter(end_date__gte=timezone.localdate())


class Booking(TimeStampedModel, PublicIdModel, ValidatedModel):
    """
    A property booking over the interval [start_date, end_date),
    where the check-out day is not part of the occupied period.
    """

    # PROTECT guards against physically deleting a listing that has bookings.
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

    start_date = models.DateField(
        verbose_name=_("Check-in"),
        help_text=_("Check-in date, inclusive. Format YYYY-MM-DD"),
    )
    end_date = models.DateField(
        verbose_name=_("Check-out"),
        help_text=_("Check-out date, exclusive: this night is not charged"),
    )
    guests = models.PositiveSmallIntegerField(
        default=1,
        # validators reject out-of-range values in full_clean() with a 400,
        # before the database CHECK would turn them into a 500.
        validators=[MinValueValidator(1), MaxValueValidator(20)],
        error_messages={
            "invalid": _("The number of guests must be a whole number."),
            "null": _("Please specify the number of guests."),
        },
        verbose_name=_("Guests"),
        help_text=_("Number of guests, from 1 to 20"),
    )
    status = models.CharField(
        max_length=16,
        choices=BookingStatus.choices,
        default=BookingStatus.PENDING,
        verbose_name=_("Status"),
        help_text=_("Lifecycle status. Changed only through the booking actions"),
    )

    # snapshots taken at booking time — the listing price and title
    # may change, and the listing may be removed altogether.

    discount_percent = models.PositiveSmallIntegerField(
        default=0,
        validators=[MaxValueValidator(100)],
        verbose_name=_("Discount, %"),
        help_text=_("Discount applied at booking time, 0 to 100 percent"),
    )
    price_per_night_snapshot = MoneyField(
        max_digits=10, decimal_places=2,
        default_currency=settings.DEFAULT_CURRENCY, editable=False,
    )
    total_price = MoneyField(
        max_digits=12, decimal_places=2,
        default_currency=settings.DEFAULT_CURRENCY, editable=False,
        verbose_name=_("Total"),
        help_text=_("Agreed contract amount, frozen at booking time"),
    )
    # the rate is frozen too. Otherwise a "revenue per quarter" report
    # would change retroactively on the next rate movement — a closed
    # period must not move.
    exchange_rate = models.DecimalField(
        max_digits=18, decimal_places=8, editable=False, default=Decimal("1"),
        verbose_name=_("Exchange rate at booking time"),
    )
    total_price_base = models.DecimalField(
        max_digits=14, decimal_places=2, editable=False, default=Decimal("0"),
        verbose_name=_("Total in base currency"),
    )
    listing_title_snapshot = models.CharField(max_length=200)

    confirmed_at = models.DateTimeField(null=True, blank=True, editable=False)
    cancelled_at = models.DateTimeField(null=True, blank=True, editable=False)

    objects = BookingQuerySet.as_manager()

    # status changes must go through save(); queryset.update() fires
    # no signals and would bypass the history.
    history = HistoricalRecords()

    class Meta:
        verbose_name = _("Booking")
        verbose_name_plural = _("Bookings")
        ordering = ("-created_at", "-id")
        permissions = [
            ("confirm_booking", "Can confirm booking"),
            ("reject_booking", "Can reject booking"),
            ("cancel_booking", "Can cancel booking"),
        ]

        constraints = [
            # violation_error_message (Django 4.1+) turns a CHECK violation
            # into a proper ValidationError during full_clean().
            models.CheckConstraint(
                condition=Q(end_date__gt=F("start_date")),
                name="booking_end_after_start",
                violation_error_message=_("The check-out date must be later than the check-in date."),
            ),
            models.CheckConstraint(
                condition=Q(guests__gte=1),
                name="booking_guests_gte_one",
                violation_error_message=_("There must be at least one guest."),
            ),
            models.CheckConstraint(
                condition=Q(total_price__gte=0),
                name="booking_total_price_gte_zero",
                violation_error_message=_("The total amount cannot be negative."),
            ),
            models.CheckConstraint(
                condition=Q(price_per_night_snapshot__gt=0),
                name="booking_snapshot_price_positive",
                violation_error_message=_("The price per night must be positive."),
            ),
            models.CheckConstraint(
                condition=Q(status__in=BookingStatus.values),
                name="booking_status_valid",
                violation_error_message=_("Invalid booking status."),
            ),
            models.CheckConstraint(
                condition=Q(discount_percent__lte=100),
                name="booking_discount_max_100",
                violation_error_message=_("The discount cannot exceed 100 percent."),
            ),
        ]

        indexes = [
            # serves overlap checks; the leading listing column is selective
            # and its prefix also serves listing-only lookups.
            models.Index(
                fields=("listing", "start_date", "end_date"),
                name="booking_listing_dates_idx",
            ),
        ]

    @classmethod
    def from_db(cls, db, field_names, values):
        """
        Remembers the status as stored, so clean() can validate the
        transition from anywhere, not only from the service layer.
        """
        instance = super().from_db(db, field_names, values)
        instance._original_status = instance.status
        return instance

    def __str__(self) -> str:
        return f"{self.listing_title_snapshot}: {self.start_date}–{self.end_date}"

    @property
    def nights(self) -> int:
        """
        Number of chargeable nights. A pure derivation of two dates,
        hence a property rather than a column.
        """
        return (self.end_date - self.start_date).days

    def calculate_total(self) -> Money:
        """
        The single place holding the total formula. Money * int and
        Money / int return Money; quantize is applied to .amount, otherwise
        a many-digit number reaches the database and MySQL rounds it
        its own way.
        """
        base = self.price_per_night_snapshot * self.nights
        discounted = base * (100 - self.discount_percent) / 100
        return Money(
            discounted.amount.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP),
            discounted.currency,
        )

    def can_transition_to(self, new_status: str) -> bool:
        """
        Whether a transition to the given status is allowed.
        """
        return new_status in STATUS_TRANSITIONS[self.status]

    def is_cancellable(self) -> bool:
        """
        Whether the cancellation deadline has not passed. The threshold
        comes from settings so the rule is not hard-coded.
        """
        deadline = self.start_date - timedelta(
            days=getattr(settings, "BOOKING_CANCELLATION_DAYS", 1)
        )
        return self.status in BLOCKING_STATUSES and timezone.localdate() <= deadline

    def save(self, *args, **kwargs):
        super().save(*args, **kwargs)
        # after the write the current status becomes the original one
        self._original_status = self.status

    def clean(self) -> None:
        """
        Rules a CHECK constraint cannot express.
        """
        errors: dict[str, ValidationError] = {}
        today = timezone.localdate()

        if self._state.adding and self.start_date and self.start_date < today:
            errors["start_date"] = ValidationError(
                _("A booking cannot start in the past."),
                code="start_date_in_past",
            )

        if self.listing_id and self.tenant_id:
            try:
                validate_not_own_listing(self.listing, self.tenant)
            except ValidationError as exc:
                errors["tenant"] = exc

        if self.listing_id and self.start_date and self.end_date:
            conflicts = Booking.objects.overlapping(
                self.listing, self.start_date, self.end_date
            ).exclude(pk=self.pk)
            if conflicts.exists():
                errors["__all__"] = ValidationError(
                    _("These dates are already booked."),
                    code="dates_taken",
                )

        original = getattr(self, "_original_status", None)
        if original is not None and original != self.status:
            if self.status not in STATUS_TRANSITIONS[original]:
                errors["status"] = ValidationError(
                    _("Transition %(old)s to %(new)s is not allowed."),
                    code="invalid_transition",
                    params={"old": original, "new": self.status},
                )
            elif self.status == BookingStatus.COMPLETED and self.end_date > today:
                errors["status"] = ValidationError(
                    _("A booking cannot be completed before the check-out date."),
                    code="completed_too_early",
                )

        if errors:
            raise ValidationError(errors)

