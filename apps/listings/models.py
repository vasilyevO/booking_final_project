from __future__ import annotations

from decimal import Decimal

from django.conf import settings
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models
from django.db.models import Q
from django.utils import timezone

from core.models import SoftDeleteModel, TimeStampedModel


class PropertyType(models.TextChoices):
    """
    RU: Тип жилья в объявлении.
    EN: Type of the advertised property.
    """

    APARTMENT = "apartment", "Квартира"
    HOUSE = "house", "Дом"
    STUDIO = "studio", "Студия"
    ROOM = "room", "Комната"


class ListingQuerySet(models.QuerySet):
    """
    RU: Переиспользуемые выборки объявлений.
    EN: Reusable listing queries.
    """

    def active(self) -> "ListingQuerySet":
        """
        RU: Только объявления, видимые арендаторам.
        EN: Only listings visible to tenants.
        """
        return self.filter(is_active=True)

    def by_owner(self, user) -> "ListingQuerySet":
        """
        RU: Объявления конкретного владельца.
        EN: Listings owned by the given user.
        """
        return self.filter(owner=user)

    def search(self, term: str) -> "ListingQuerySet":
        """
        RU: Поиск по заголовку и описанию. icontains даёт LIKE '%...%',
            индекс не используется — при росте данных нужен FULLTEXT.
        EN: Search over title and description. icontains compiles to LIKE '%...%',
            which cannot use an index — FULLTEXT is required at scale.
        """
        if not term:
            return self
        return self.filter(Q(title__icontains=term) | Q(description__icontains=term))

    def with_related(self) -> "ListingQuerySet":
        """
        RU: Снимает проблему N+1: select_related для ForeignKey, prefetch_related
            для обратных связей.
        EN: Solves the N+1 problem: select_related for foreign keys, prefetch_related
            for reverse relations.
        """
        return self.select_related("owner").prefetch_related("reviews")


class ListingManager(models.Manager.from_queryset(ListingQuerySet)):
    """
    RU: Менеджер по умолчанию, скрывающий удалённые объявления.
    EN: Default manager hiding soft-deleted listings.
    """

    def get_queryset(self) -> ListingQuerySet:
        return super().get_queryset().filter(deleted_at__isnull=True)


class Listing(TimeStampedModel, SoftDeleteModel):
    """
    RU: Объявление о сдаче жилья.
    EN: Rental property listing.
    """

    # RU: ссылаемся через settings.AUTH_USER_MODEL, а не импортом User.
    # EN: reference settings.AUTH_USER_MODEL instead of importing User directly.
    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="listings",
        verbose_name="Владелец",
    )
    title = models.CharField(max_length=200)
    description = models.TextField()

    city = models.CharField(max_length=100, db_index=True)
    district = models.CharField(max_length=100, blank=True, db_index=True)
    address = models.CharField(max_length=255)
    postal_code = models.CharField(max_length=16, blank=True)

    # RU: Decimal, а не Float — двоичная плавающая точка теряет копейки.
    # EN: Decimal rather than Float — binary floating point loses cents.
    price_per_night = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        validators=[MinValueValidator(Decimal("0.01"))],
    )
    rooms = models.PositiveSmallIntegerField(
        validators=[MinValueValidator(1), MaxValueValidator(50)]
    )
    property_type = models.CharField(
        max_length=16, choices=PropertyType.choices, db_index=True
    )

    # RU: is_active — временное скрытие; deleted_at — удаление владельцем.
    # EN: is_active is a temporary hide; deleted_at is an owner-initiated removal.
    is_active = models.BooleanField(default=True, db_index=True)
    views_count = models.PositiveIntegerField(default=0, editable=False)

    objects = ListingManager()
    all_objects = models.Manager.from_queryset(ListingQuerySet)()

    class Meta:
        verbose_name = "Объявление"
        verbose_name_plural = "Объявления"
        # RU: -id как tie-breaker — иначе пагинация нестабильна.
        # EN: -id as a tie-breaker — otherwise pagination is unstable.
        ordering = ("-created_at", "-id")
        base_manager_name = "all_objects"
        constraints = [
            models.CheckConstraint(
                condition=Q(price_per_night__gt=0), name="listing_price_gt_zero"
            ),
            models.CheckConstraint(condition=Q(rooms__gte=1), name="listing_rooms_gte_one"),
        ]
        indexes = [
            models.Index(fields=("city", "price_per_night"), name="listing_city_price_idx"),
            models.Index(fields=("property_type", "is_active"), name="listing_type_act_idx"),
        ]

    def __str__(self) -> str:
        return f"{self.title} ({self.city})"

    def has_future_bookings(self) -> bool:
        """
        RU: Есть ли активные брони, заканчивающиеся сегодня или позже.
            Определяет, можно ли удалить объявление физически.
        EN: Whether active bookings ending today or later exist.
            Decides if the listing may be deleted physically.
        """
        from apps.bookings.models import BLOCKING_STATUSES

        return self.bookings.filter(
            status__in=BLOCKING_STATUSES,
            end_date__gte=timezone.localdate(),
        ).exists()