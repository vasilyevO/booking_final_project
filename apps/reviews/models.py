from __future__ import annotations

from datetime import timedelta

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models
from django.db.models import Q
from django.utils import timezone
from simple_history.models import HistoricalRecords

from core.models import SoftDeleteModel, TimeStampedModel, ValidatedModel


class Review(TimeStampedModel, SoftDeleteModel, ValidatedModel):
    """
    RU: Отзыв об объявлении. Привязан к бронированию, поэтому оставить отзыв
        без факта аренды структурно невозможно. Удаление только мягкое, чтобы
        владелец не мог обнулить репутацию, удалив объявление и создав новое.
    EN: A listing review. Bound to a booking, so a review without an actual stay
        is structurally impossible. Deletion is soft only, so an owner cannot
        reset their reputation by removing a listing and recreating it.
    """

    # RU: PROTECT вместо CASCADE — удаление брони или объявления не должно
    #     уносить отзывы вместе с собой.
    # EN: PROTECT instead of CASCADE — deleting a booking or a listing must not
    #     take the reviews down with it.
    booking = models.OneToOneField(
        "bookings.Booking", on_delete=models.PROTECT, related_name="review"
    )
    # RU: денормализация ради быстрой выборки «все отзывы объявления».
    # EN: denormalised for fast "all reviews of a listing" queries.
    listing = models.ForeignKey(
        "listings.Listing",
        on_delete=models.PROTECT,
        related_name="reviews",
        editable=False,
    )
    author = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        related_name="reviews",
        editable=False,
    )

    # RU: validators дают понятную 400-ю ошибку в DRF, а CheckConstraint
    #     защищает от bulk_create, который не вызывает валидацию.
    # EN: validators produce a readable 400 in DRF, while the CheckConstraint
    #     guards against bulk_create, which skips validation.
    rating = models.PositiveSmallIntegerField(
        validators=[MinValueValidator(1), MaxValueValidator(5)],
        verbose_name="Оценка",
        help_text="Rating from 1 to 5",
    )
    text = models.TextField(
        max_length=2000,
        blank=True,
        verbose_name="Текст",
        help_text="Free-form review, up to 2000 characters",
    )

    history = HistoricalRecords()

    class Meta:
        verbose_name = "Отзыв"
        verbose_name_plural = "Отзывы"
        ordering = ("-created_at", "-id")
        base_manager_name = "all_objects"
        constraints = [
            models.CheckConstraint(
                condition=Q(rating__gte=1) & Q(rating__lte=5),
                name="review_rating_range",
            ),
        ]
        indexes = [
            models.Index(fields=("listing", "-created_at"), name="review_listing_created_idx")
        ]

    def __str__(self) -> str:
        return f"{self.rating}★ — {self.listing_id}"

    @property
    def is_editable(self) -> bool:
        """
        RU: Отзыв правится только в течение окна редактирования после
            публикации. Порог берётся из настроек, чтобы правило не было
            зашито в код. Свойство читает core.permissions.IsReviewAuthor.
        EN: A review may be edited only within the edit window after it was
            posted. The threshold comes from settings so the rule is not
            hard-coded. Read by core.permissions.IsReviewAuthor.
        """
        window = timedelta(days=getattr(settings, "REVIEW_EDIT_WINDOW_DAYS", 14))
        return timezone.now() - self.created_at <= window

    def clean(self) -> None:
        """
        RU: Отзыв возможен только после фактически завершённого проживания.
        EN: A review is only allowed after the stay has actually ended.
        """
        from apps.bookings.models import BookingStatus

        if self.booking_id:
            if self.booking.status != BookingStatus.COMPLETED:
                raise ValidationError("Отзыв можно оставить только после завершения аренды.")
            if self.booking.end_date > timezone.localdate():
                raise ValidationError("Проживание ещё не закончилось.")

    def save(self, *args, **kwargs) -> None:
        """
        RU: Заполняет денормализованные поля из брони — источник истины один.
        EN: Fills denormalised fields from the booking — a single source of truth.
        """
        self.listing_id = self.booking.listing_id
        self.author_id = self.booking.tenant_id
        super().save(*args, **kwargs)