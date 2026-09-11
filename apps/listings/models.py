from __future__ import annotations

from decimal import Decimal

from django.conf import settings
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models
from django.db.models import Q
from django.utils import timezone
from simple_history.models import HistoricalRecords
from django.db.models.expressions import RawSQL
import uuid
from pathlib import Path

from core.models import PublicIdModel, SoftDeleteModel, TimeStampedModel


class PropertyType(models.TextChoices):
    """
    RU: Тип жилья в объявлении.
    EN: Type of the advertised property.
    """

    APARTMENT = "apartment", "Квартира"
    HOUSE = "house", "Дом"
    STUDIO = "studio", "Студия"
    ROOM = "room", "Комната"

def listing_photo_path(instance: "ListingPhoto", filename: str) -> str:
    """
    RU: Имя файла из UUID: два пользователя могут загрузить photo.jpg,
        и второй перезаписал бы первого.
    EN: UUID-based filename: two users may upload photo.jpg, and the
        second would otherwise overwrite the first.
    """
    suffix = Path(filename).suffix.lower()
    return f"listings/{instance.listing_id}/{uuid.uuid4().hex}{suffix}"


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
        RU: Полнотекстовый поиск по FULLTEXT-индексу с сортировкой по релевантности.
            Слова короче innodb_ft_min_token_size (по умолчанию 3) не индексируются.
        EN: Full-text search over the FULLTEXT index, ordered by relevance.
            Words shorter than innodb_ft_min_token_size (3 by default) are not indexed.
        """
        if not term:
            return self
        # RU: параметр передаём отдельно — форматирование строки было бы инъекцией
        # EN: pass the parameter separately — string formatting would be an injection
        relevance = RawSQL("MATCH(title, description) AGAINST (%s IN BOOLEAN MODE)", (term,))
        return self.annotate(relevance=relevance).filter(relevance__gt=0)

    def search_fallback(self, term: str) -> "ListingQuerySet":
        """
        RU: Запасной путь для коротких слов: LIKE '%...%', индекс не используется.
        EN: Fallback for short words: LIKE '%...%', no index is used.
        """
        if not term:
            return self
        return self.filter(Q(title__icontains=term) | Q(description__icontains=term))

    def with_related(self) -> "ListingQuerySet":
        """
        RU: Снимает проблему N+1: select_related для ForeignKey,
            prefetch_related для обратных связей.
        EN: Solves the N+1 problem: select_related for foreign keys,
            prefetch_related for reverse relations.
        """
        return self.select_related("owner").prefetch_related("reviews")


class ListingManager(models.Manager.from_queryset(ListingQuerySet)):
    """
    RU: Менеджер по умолчанию, скрывающий удалённые объявления.
    EN: Default manager hiding soft-deleted listings.
    """

    def get_queryset(self) -> ListingQuerySet:
        return super().get_queryset().filter(deleted_at__isnull=True)


class Listing(TimeStampedModel, SoftDeleteModel, PublicIdModel):
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
    title = models.CharField(
        max_length=200,
        verbose_name="Заголовок",
        help_text="Short headline shown in search results, e.g. 'Bright 2-room flat near Rhine'",
    )
    description = models.TextField(
        verbose_name="Описание",
        help_text="Full description: layout, furniture, neighbourhood, house rules",
    )
    city = models.CharField(
        max_length=100,
        db_index=True,
        verbose_name="Город",
        help_text="City in Germany, e.g. Köln. Stored normalised for search",
    )
    district = models.CharField(
        max_length=100,
        blank=True,
        verbose_name="Район",
        help_text="District or quarter, optional",
    )
    price_per_night = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        validators=[MinValueValidator(Decimal("0.01"))],
        verbose_name="Цена за ночь",
        help_text="Price per night in EUR, e.g. 89.50",
    )
    rooms = models.PositiveSmallIntegerField(
        validators=[MinValueValidator(1), MaxValueValidator(50)],
        verbose_name="Комнат",
        help_text="Number of rooms, from 1 to 50",
    )
    property_type = models.CharField(
        max_length=16,
        choices=PropertyType.choices,
        verbose_name="Тип жилья",
        help_text="apartment, house, studio or room",
    )
    is_active = models.BooleanField(
        default=True,
        verbose_name="Активно",
        help_text="Inactive listings are hidden from search but keep their bookings",
    )
    views_count = models.PositiveIntegerField(default=0, editable=False)

    objects = ListingManager()
    all_objects = models.Manager.from_queryset(ListingQuerySet)()

    # RU: views_count исключён — иначе каждый просмотр породит запись истории
    # EN: views_count excluded — otherwise every view would create a history row
    history = HistoricalRecords(excluded_fields=["views_count"])

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
            # RU: Django НЕ переносит choices в БД — колонка остаётся обычным
            #     varchar. Только явный CHECK защищает от bulk_create.
            # EN: Django does NOT push choices to the database — the column is a
            #     plain varchar. Only an explicit CHECK guards against bulk_create.
            models.CheckConstraint(
                condition=Q(property_type__in=PropertyType.values),
                name="listing_property_type_valid",
            ),
        ]
        indexes = [
            # RU: порядок колонок: равенство, равенство, диапазон.
            #     Диапазон обрывает использование индекса, поэтому он последний.
            #     Этот же индекс обслуживает ORDER BY price_per_night.
            # EN: column order: equality, equality, range.
            #     A range stops further index usage, so it comes last.
            #     The same index also serves ORDER BY price_per_night.
            models.Index(
                fields=("city", "rooms", "price_per_night"),
                name="listing_city_rooms_price_idx",
            ),
            # RU: rooms и property_type не могут оба стоять вторыми — нужен
            #     второй индекс под вторую форму запроса.
            # EN: rooms and property_type cannot both be second — a second index
            #     is required for the second query shape.
            models.Index(
                fields=("city", "property_type", "price_per_night"),
                name="listing_city_type_price_idx",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.title} ({self.city})"

    def has_future_bookings(self) -> bool:
        """
        RU: Есть ли активные брони, заканчивающиеся сегодня или позже.
        EN: Whether active bookings ending today or later exist.
        """
        from apps.bookings.models import BLOCKING_STATUSES

        return self.bookings.filter(
            status__in=BLOCKING_STATUSES,
            end_date__gte=timezone.localdate(),
        ).exists()

class ListingPhoto(TimeStampedModel):
    """
    RU: Фотография объявления. Порядок задаётся полем position,
        обложкой считается фото с наименьшим значением.
    EN: A listing photo. Ordering is driven by the position field;
        the photo with the lowest value acts as the cover.
    """

    listing = models.ForeignKey(
        "listings.Listing", on_delete=models.CASCADE, related_name="photos"
    )
    image = models.ImageField(
        upload_to=listing_photo_path,
        verbose_name="Фото",
        help_text="JPEG or PNG, at least 800x600 px",
    )
    caption = models.CharField(
        max_length=200,
        blank=True,
        verbose_name="Подпись",
        help_text="Optional caption, e.g. 'Living room'",
    )
    position = models.PositiveSmallIntegerField(
        default=0,
        verbose_name="Позиция",
        help_text="Display order, ascending. The lowest value is the cover photo",
    )

    class Meta:
        verbose_name = "Фото объявления"
        verbose_name_plural = "Фото объявлений"
        # RU: id как tie-breaker при равных позициях — порядок детерминирован
        # EN: id as a tie-breaker for equal positions — deterministic ordering
        ordering = ("position", "id")
        # RU: UniqueConstraint на (listing, position) НЕ ставим: перестановка
        #     двух фото требовала бы промежуточного дубля, а отложенных
        #     ограничений в MySQL нет.
        # EN: no UniqueConstraint on (listing, position): swapping two photos
        #     would need a transient duplicate, and MySQL has no deferred
        #     constraints.
        indexes = [
            models.Index(fields=("listing", "position"), name="photo_listing_pos_idx"),
        ]

    def __str__(self) -> str:
        return f"photo {self.pk} of listing {self.listing_id}"
