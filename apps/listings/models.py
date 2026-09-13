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

from core.models import PublicIdModel, SoftDeleteModel, TimeStampedModel, ValidatedModel
from core.text import normalize_search_text


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

# RU: FULLTEXT не индексирует слова короче innodb_ft_min_token_size
# EN: FULLTEXT does not index words shorter than innodb_ft_min_token_size
MIN_FULLTEXT_TOKEN = 3

def search(self, term: str) -> "ListingQuerySet":
    """
    RU: Полнотекстовый поиск по FULLTEXT-индексу с сортировкой по
        релевантности. Для коротких слов автоматически падает на LIKE,
        который индекс не использует, но хотя бы что-то находит.
    EN: Full-text search over the FULLTEXT index, ordered by relevance.
        Short words automatically fall back to LIKE, which cannot use an
        index but at least returns something.
    """
    term = (term or "").strip()
    if not term:
        return self

    if len(term) < self.MIN_FULLTEXT_TOKEN:
        return self.filter(Q(title__icontains=term) | Q(description__icontains=term))

    # RU: параметр передаём отдельно — форматирование строки было бы инъекцией
    # EN: pass the parameter separately — string formatting would be injection
    relevance = RawSQL("MATCH(title, description) AGAINST (%s IN BOOLEAN MODE)", (term,))
    return self.annotate(relevance=relevance).filter(relevance__gt=0)

def with_related(self) -> "ListingQuerySet":
    """
    RU: Снимает N+1 для карточек списка: владелец, фото и статистика.
    EN: Removes N+1 for list cards: owner, photos and stats.
    """
    return self.select_related("owner", "stats").prefetch_related("photos")

class ListingManager(models.Manager.from_queryset(ListingQuerySet)):
    """
    RU: Менеджер по умолчанию, скрывающий удалённые объявления.
    EN: Default manager hiding soft-deleted listings.
    """

    def get_queryset(self) -> ListingQuerySet:
        return super().get_queryset().filter(deleted_at__isnull=True)


class Listing(TimeStampedModel, SoftDeleteModel, PublicIdModel, ValidatedModel):
    """
    RU: Объявление о сдаче жилья.
    EN: Rental property listing.
    """

    # RU: ссылаемся через settings.AUTH_USER_MODEL, а не импортом User.
    # EN: reference settings.AUTH_USER_MODEL instead of importing User directly.
    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        # RU: CASCADE был опасен: удаление пользователя каскадно сносило его
        #     объявления, но у объявлений PROTECT от броней — каскад падал
        #     посередине с ProtectedError. Пользователей деактивируем
        #     (is_active=False), а не удаляем.
        # EN: CASCADE was dangerous: deleting a user cascaded into their
        #     listings, which are PROTECTed by bookings — the cascade failed
        #     halfway with ProtectedError. Users are deactivated
        #     (is_active=False) rather than deleted.
        on_delete=models.PROTECT,
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
        # RU: db_index убран — city уже ведущая колонка составных индексов,
        #     левый префикс обслуживает поиск только по городу.
        # EN: db_index dropped — city already leads the composite indexes,
        #     whose leftmost prefix serves city-only lookups.
        verbose_name="Город",
        help_text="City as displayed, e.g. Köln",
    )
    city_normalized = models.CharField(
        max_length=100,
        editable=False,
        db_index=True,
        verbose_name="Город (поиск)",
        help_text="Folded lowercase form used for search: Köln, Koeln and koln all become koeln",
    )
    district = models.CharField(
        max_length=100,
        blank=True,
        verbose_name="Район",
        help_text="District or quarter, optional",
    )
    address = models.CharField(
        max_length=200,
        blank=True,
        verbose_name="Адрес",
        help_text="Street and house number, e.g. Hohe Straße 12. Optional",
    )
    postal_code = models.CharField(
        max_length=16,
        blank=True,
        verbose_name="Индекс",
        help_text="Postal code, e.g. 50667. Optional",
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

    objects = ListingManager()
    all_objects = models.Manager.from_queryset(ListingQuerySet)()

    # RU: поле views_count удалено. UPDATE счётчика шёл по той же строке,
    #     которую create_booking() держит под select_for_update — просмотры
    #     конкурировали с оформлением броней за одну блокировку.
    #     Счётчик переехал в analytics.ListingStats.
    # EN: the views_count field is gone. Its UPDATE hit the very row that
    #     create_booking() holds under select_for_update — views competed with
    #     booking creation for the same lock. The counter now lives in
    #     analytics.ListingStats.

    # RU: excluded_fields больше не нужен — исключать нечего
    # EN: excluded_fields is no longer needed — there is nothing to exclude
    history = HistoricalRecords()

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
            models.Index(
                fields=("city_normalized", "rooms", "price_per_night"),
                name="listing_city_rooms_price_idx",
            ),
            models.Index(
                fields=("city_normalized", "property_type", "price_per_night"),
                name="listing_city_type_price_idx",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.title} ({self.city})"

    def save(self, *args, **kwargs):
        """
        RU: Пересчитывает нормализованный город перед сохранением. Источник
            истины один — поле city; клиент city_normalized не передаёт.
        EN: Recomputes the normalised city before saving. There is one source of
            truth — the city field; the client never supplies city_normalized.
        """
        self.city_normalized = normalize_search_text(self.city)
        update_fields = kwargs.get("update_fields")
        if update_fields is not None and "city" in set(update_fields):
            kwargs["update_fields"] = list(set(update_fields) | {"city_normalized"})
        return super().save(*args, **kwargs)

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
