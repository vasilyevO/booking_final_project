from __future__ import annotations

from drf_spectacular.utils import extend_schema_field
from rest_framework import serializers

from .models import Listing, ListingPhoto


class ListingPhotoSerializer(serializers.ModelSerializer):
    """
    RU: Фотография объявления.
    EN: A listing photo.
    """

    class Meta:
        model = ListingPhoto
        fields = ("id", "image", "caption", "position")
        read_only_fields = ("id",)


class PhotoReorderSerializer(serializers.Serializer):
    """
    RU: Новый порядок фото: полный список id в нужной последовательности.
    EN: New photo order: the complete list of ids in the desired sequence.
    """

    photo_ids = serializers.ListField(
        child=serializers.IntegerField(),
        allow_empty=False,
        help_text="All photo ids of this listing, in the desired display order",
    )


class ListingListSerializer(serializers.ModelSerializer):
    """
    RU: Краткое представление для списка и поиска.
    EN: Compact representation for list and search results.
    """

    owner_email = serializers.EmailField(source="owner.email", read_only=True)
    # RU: значения приходят из annotate() во вьюсете. SerializerMethodField
    #     с aggregate() дал бы запрос на каждый объект списка — N+1.
    # EN: values come from annotate() in the viewset. A SerializerMethodField
    #     with aggregate() would issue one query per row — the N+1 problem.
    rating = serializers.FloatField(read_only=True, default=None)
    reviews_count = serializers.IntegerField(read_only=True, default=0)
    cover_photo = serializers.SerializerMethodField()

    class Meta:
        model = Listing
        fields = (
            "public_id", "title", "city", "district", "property_type",
            "rooms", "price_per_night", "is_active",
            "rating", "reviews_count", "cover_photo", "owner_email", "created_at",
        )

    @extend_schema_field(serializers.CharField(allow_null=True))
    def get_cover_photo(self, obj: Listing) -> str | None:
        """
        RU: Обложка — фото с наименьшим position. Полагается на
            prefetch_related("photos") из ListingQuerySet.with_related():
            без него каждое объявление в списке даст свой запрос.
        EN: The cover is the photo with the lowest position. Relies on
            prefetch_related("photos") from ListingQuerySet.with_related():
            without it every listing in the list costs a query.
        """
        photos = obj.photos.all()
        photo = photos[0] if photos else None
        return photo.image.url if photo else None


class ListingDetailSerializer(ListingListSerializer):
    """
    RU: Полная карточка объявления со всеми фото.
    EN: Full listing card including all photos.
    """

    photos = ListingPhotoSerializer(many=True, read_only=True)
    # RU: счётчик живёт в analytics.ListingStats — отдельная таблица, чтобы
    #     просмотры не конкурировали за строку объявления с оформлением броней.
    # EN: the counter lives in analytics.ListingStats — a separate table, so
    #     views do not contend for the listing row with booking creation.
    views_count = serializers.IntegerField(
        source="stats.views_count", read_only=True, default=0
    )

    class Meta(ListingListSerializer.Meta):
        fields = ListingListSerializer.Meta.fields + (
            "description", "address", "postal_code", "photos", "views_count", "updated_at",
        )


class ListingWriteSerializer(serializers.ModelSerializer):
    """
    RU: Создание и редактирование. Владелец подставляется из запроса,
        клиент передать его не может.
    EN: Create and update. The owner is taken from the request; the client
        cannot supply it.
    """

    # RU: HiddenField не виден ни в схеме, ни в форме, но попадает
    #     в validated_data — иначе можно создать объявление от чужого имени.
    # EN: HiddenField appears neither in the schema nor in the form, yet lands
    #     in validated_data — otherwise one could post on another user's behalf.
    owner = serializers.HiddenField(default=serializers.CurrentUserDefault())

    class Meta:
        model = Listing
        fields = (
            "public_id", "owner", "title", "description", "city", "district",
            "address", "postal_code", "price_per_night", "rooms",
            "property_type", "is_active",
        )
        read_only_fields = ("public_id",)

    def validate_city(self, value: str) -> str:
        """
        RU: Убираем лишние пробелы у отображаемого значения. Свёрнутую форму
            для поиска считает Listing.save() в поле city_normalized —
            приводить city к нижнему регистру нельзя, оно видно пользователю.
        EN: Trim the displayed value only. The folded search form is computed by
            Listing.save() into city_normalized — city itself must not be
            lowercased, it is shown to the user.
        """
        return value.strip()

    # RU: межполевых проверок здесь нет намеренно — инварианты живут
    #     в Listing.clean() и в CheckConstraint, а full_clean() вызывается
    #     из ValidatedModel.save().
    # EN: no cross-field checks here on purpose — invariants live in
    #     Listing.clean() and in CheckConstraints, and full_clean() is invoked
    #     by ValidatedModel.save().