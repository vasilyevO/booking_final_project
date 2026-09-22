from __future__ import annotations

from drf_spectacular.utils import extend_schema_field
from rest_framework import serializers
from djmoney.contrib.django_rest_framework import MoneyField as MoneySerializerField
from .models import Listing, ListingPhoto
from django.utils.translation import gettext_lazy as _


class ListingPhotoSerializer(serializers.ModelSerializer):
    """
    A listing photo.
    """

    class Meta:
        model = ListingPhoto
        fields = ("id", "image", "caption", "position")
        read_only_fields = ("id",)


class PhotoReorderSerializer(serializers.Serializer):
    """
    New photo order: the complete list of ids in the desired sequence.
    """

    photo_ids = serializers.ListField(
        child=serializers.IntegerField(),
        allow_empty=False,
        help_text=_("All photo ids of this listing, in the desired display order"),
    )


class ListingListSerializer(serializers.ModelSerializer):
    """
    Compact representation for list and search results.
    """

    owner_email = serializers.EmailField(source="owner.email", read_only=True)
    # values come from annotate() in the viewset. A SerializerMethodField
    # with aggregate() would issue one query per row — the N+1 problem.
    rating = serializers.FloatField(read_only=True, default=None)
    reviews_count = serializers.IntegerField(read_only=True, default=0)
    cover_photo = serializers.SerializerMethodField()
    price_per_night = MoneySerializerField(max_digits=10, decimal_places=2)
    # the currency column is exposed as its own field, so it is visible
    # both in the JSON and in the OpenAPI schema.
    price_per_night_currency = serializers.CharField(read_only=True)

    class Meta:
        model = Listing
        fields = (
            "public_id", "title", "city", "district", "property_type",
            "rooms", "price_per_night", "price_per_night_currency",
            "is_active", "rating", "reviews_count", "cover_photo",
            "owner_email", "created_at",
        )

    @extend_schema_field(serializers.CharField(allow_null=True))
    def get_cover_photo(self, obj: Listing) -> str | None:
        """
        The cover is the photo with the lowest position. Relies on
        prefetch_related("photos") from ListingQuerySet.with_related():
        without it every listing in the list costs a query.
        """
        photos = obj.photos.all()
        photo = photos[0] if photos else None
        return photo.image.url if photo else None


class ListingDetailSerializer(ListingListSerializer):
    """
    Full listing card including all photos.
    """

    photos = ListingPhotoSerializer(many=True, read_only=True)
    # the counter lives in analytics.ListingStats — a separate table, so
    # views do not contend for the listing row with booking creation.
    views_count = serializers.IntegerField(
        source="stats.views_count", read_only=True, default=0
    )

    class Meta(ListingListSerializer.Meta):
        fields = ListingListSerializer.Meta.fields + (
            "description", "address", "postal_code", "photos", "views_count", "updated_at",
        )


class ListingWriteSerializer(serializers.ModelSerializer):
    """
    Create and update. The owner is taken from the request; the client
    cannot supply it.
    """

    # HiddenField appears neither in the schema nor in the form, yet lands
    # in validated_data — otherwise one could post on another user's behalf.
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
        Trim the displayed value only. The folded search form is computed by
        Listing.save() into city_normalized — city itself must not be
        lowercased, it is shown to the user.
        """
        return value.strip()

    # no cross-field checks here on purpose — invariants live in
    # Listing.clean() and in CheckConstraints, and full_clean() is invoked
    # by ValidatedModel.save().