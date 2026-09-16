from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal

from django.conf import settings
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models
from django.db.models import Q
from django.utils import timezone
from simple_history.models import HistoricalRecords
from django.db.models.expressions import RawSQL
import uuid
from pathlib import Path
from django.utils.translation import gettext_lazy as _
from djmoney.models.fields import MoneyField
from djmoney.models.validators import MinMoneyValidator
from djmoney.contrib.exchange.models import convert_money
from djmoney.money import Money
from django.utils.translation import get_language

from core.models import PublicIdModel, SoftDeleteModel, TimeStampedModel, ValidatedModel
from core.text import normalize_search_text


class PropertyType(models.TextChoices):
    """
    RU: Тип жилья в объявлении.
    EN: Type of the advertised property.
    """

    APARTMENT = "apartment", _("Apartment")
    HOUSE = "house", _("House")
    STUDIO = "studio", _("Studio")
    ROOM = "room", _("Room")

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
        RU: Ищет по колонкам активного языка. Имя колонки подставляется из
            белого списка MODELTRANSLATION_LANGUAGES, не из запроса —
            в SQL параметризовать имя колонки нельзя, и без белого списка
            это была бы инъекция.
        EN: Searches the active language's columns. The column name comes from
            the MODELTRANSLATION_LANGUAGES allowlist, never from the request:
            a column name cannot be parameterised in SQL, and without the
            allowlist this would be an injection.
        """
        term = (term or "").strip()
        if not term:
            return self

        lang = get_language() or settings.MODELTRANSLATION_DEFAULT_LANGUAGE
        if lang not in settings.MODELTRANSLATION_LANGUAGES:
            lang = settings.MODELTRANSLATION_DEFAULT_LANGUAGE

        if len(term) < self.MIN_FULLTEXT_TOKEN:
            return self.filter(
                Q(**{f"title_{lang}__icontains": term})
                | Q(**{f"description_{lang}__icontains": term})
            )

        # RU: BOOLEAN MODE — это свой мини-язык: + - > < ( ) ~ * " @ в нём
        #     операторы. Параметризация от этого не спасает, значение всё равно
        #     разбирает парсер MySQL, и «++a» падало ошибкой 1064, то есть 500.
        #     Экранирования в этом языке нет — единственный надёжный приём
        #     это привести запрос к списку фраз в кавычках.
        # EN: BOOLEAN MODE is a little language of its own: + - > < ( ) ~ * " @
        #     are operators in it. Parameterisation does not help, since MySQL's
        #     own parser still reads the value, and "++a" failed with error 1064,
        #     i.e. a 500. That language has no escape syntax — the only reliable
        #     approach is to reduce the query to a list of quoted phrases.
        phrases = self._as_boolean_phrases(term)
        if not phrases:
            return self.none()

        relevance = RawSQL(
            f"MATCH(title_{lang}, description_{lang}) AGAINST (%s IN BOOLEAN MODE)",
            (phrases,),
        )
        return self.annotate(relevance=relevance).filter(relevance__gt=0)

    @staticmethod
    def _as_boolean_phrases(term: str) -> str:
        """
        RU: Превращает пользовательский ввод в безопасный запрос BOOLEAN MODE:
            слова внутри кавычек парсер читает буквально, поэтому операторы
            теряют силу. Кавычки из ввода вырезаются — иначе фразу можно
            закрыть досрочно и вернуть операторы обратно.
        EN: Turns user input into a safe BOOLEAN MODE query: inside quotes the
            parser reads words literally, so the operators lose their meaning.
            Quotes from the input are dropped — otherwise a phrase could be
            closed early and the operators brought back.
        """
        words = [word.strip('"').strip() for word in term.replace('"', " ").split()]
        return " ".join(f'"{word}"' for word in words if word)

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
    # RU: MoneyField — это ДВЕ колонки: price_per_night (decimal) и
    #     price_per_night_currency (varchar(3)). В Python — один Money.
    # EN: a MoneyField is TWO columns: price_per_night (decimal) and
    #     price_per_night_currency (varchar(3)). In Python it is one Money.
    price_per_night = MoneyField(
        max_digits=10,
        decimal_places=2,
        default_currency=settings.DEFAULT_CURRENCY,
        # RU: MinValueValidator сравнивает Money с Decimal, а py-moneyed на
        #     таком сравнении бросает MoneyComparisonError — full_clean() падал
        #     на КАЖДОМ сохранении объявления. MinMoneyValidator сравнивает
        #     суммы, приводя валюту.
        # EN: MinValueValidator compares Money against a Decimal, and py-moneyed
        #     raises MoneyComparisonError on that — full_clean() failed on EVERY
        #     listing save. MinMoneyValidator compares amounts, handling currency.
        validators=[MinMoneyValidator(Decimal("0.01"))],
        verbose_name=_("Price per night"),
        help_text=_("Price per one night in the chosen currency, e.g. 89.50"),
    )
    # RU: денормализованная цена в базовой валюте. Нужна потому, что фильтр
    #     price__lte=100 сравнивает числа и игнорирует колонку валюты:
    #     100 USD, 100 PLN и 100 EUR встали бы рядом. Тот же приём, что
    #     city_normalized: авторитетное значение отдельно, поисковое отдельно.
    # EN: denormalised price in the base currency. Needed because a
    #     price__lte=100 filter compares numbers and ignores the currency
    #     column: 100 USD, 100 PLN and 100 EUR would rank together. The same
    #     pattern as city_normalized: the authoritative value and the
    #     searchable one are separate columns.
    price_base = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        editable=False,
        # RU: заполнитель для уже существующих строк при миграции. Реальное
        #     значение всегда пересчитывает Listing.save() до full_clean().
        # EN: a filler for rows that already exist when the migration runs. The
        #     real value is always recomputed by Listing.save() before full_clean().
        default=Decimal("0"),
        db_index=False,
        verbose_name=_("Price in base currency"),
        help_text=_("Computed automatically, used for filtering and sorting"),
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
                condition=Q(price_per_night__gt=0),
                name="listing_price_gt_zero",
                violation_error_message=_("Price must be greater than zero."),
            ),
            # RU: колонка валюты — обычный varchar. Django не переносит в БД
            #     ни choices, ни список CURRENCIES, поэтому CHECK обязателен.
            # EN: the currency column is a plain varchar. Django pushes neither
            #     choices nor the CURRENCIES list to the database, so the CHECK
            #     is mandatory.
            models.CheckConstraint(
                condition=Q(price_per_night_currency__in=settings.CURRENCIES),
                name="listing_currency_valid",
                violation_error_message=_("Unsupported currency."),
            ),
            models.CheckConstraint(
                condition=Q(rooms__gte=1),
                name="listing_rooms_gte_one",
                violation_error_message=_("A listing must have at least one room."),
            ),
            models.CheckConstraint(
                condition=Q(property_type__in=PropertyType.values),
                name="listing_property_type_valid",
                violation_error_message=_("Unknown property type."),
            ),
        ]
        indexes = [
            # RU: индексы переехали с price_per_night на price_base —
            #     сортировка по смешанным валютам была бы неверной.
            # EN: the indexes moved from price_per_night to price_base —
            #     sorting across mixed currencies would be wrong.
            models.Index(
                fields=("city_normalized", "rooms", "price_base"),
                name="listing_city_rooms_price_idx",
            ),
            models.Index(
                fields=("city_normalized", "property_type", "price_base"),
                name="listing_city_type_price_idx",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.title} ({self.city})"

    def save(self, *args, **kwargs):
        """
        RU: Пересчитывает производные поля до full_clean(): нормализованный
            город и цену в базовой валюте. Оба объявлены без blank=True,
            поэтому порядок важен — иначе валидация упадёт на пустом поле.
        EN: Recomputes the derived fields before full_clean(): the normalised
            city and the base-currency price. Neither allows blank, so the
            order matters — otherwise validation fails on an empty field.
        """
        self.city_normalized = normalize_search_text(self.city)
        self.price_base = self._to_base_currency(self.price_per_night)

        update_fields = kwargs.get("update_fields")
        if update_fields is not None:
            names = set(update_fields)
            # RU: при частичном сохранении производные поля надо добавить
            #     в список явно, иначе UPDATE их не запишет.
            # EN: on a partial save the derived fields must be added to the
            #     list explicitly, otherwise the UPDATE skips them.
            if "city" in names:
                names.add("city_normalized")
            if "price_per_night" in names or "price_per_night_currency" in names:
                names.add("price_base")
            kwargs["update_fields"] = list(names)

        return super().save(*args, **kwargs)

    @staticmethod
    def _to_base_currency(amount: Money) -> Decimal:
        """
        RU: Приводит сумму к базовой валюте. Если курсы ещё не загружены
            командой update_rates, падать нельзя — отдаём исходное число.
        EN: Converts an amount into the base currency. If the rates have not
            been loaded by update_rates yet, do not fail — return the raw value.
        """
        if amount is None:
            return Decimal("0")
        if str(amount.currency) == settings.BASE_CURRENCY:
            return amount.amount
        try:
            converted = convert_money(amount, settings.BASE_CURRENCY).amount
        except Exception:
            return amount.amount
        # RU: convert_money делит на курс и возвращает Decimal полной точности —
        #     250 CZK дают 9.96015936254980079681274900 EUR, а это 28 знаков
        #     при max_digits=12. Без округления full_clean() отклоняет
        #     любую цену в неевровой валюте.
        # EN: convert_money divides by the rate and returns a full-precision
        #     Decimal — 250 CZK become 9.96015936254980079681274900 EUR, i.e. 28
        #     digits against max_digits=12. Without rounding, full_clean()
        #     rejects every non-EUR price.
        return converted.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)

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
