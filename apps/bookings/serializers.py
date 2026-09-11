from __future__ import annotations

from drf_spectacular.utils import extend_schema_field
from rest_framework import serializers

from apps.listings.models import Listing
from .models import Booking, BookingStatus
from .services import create_booking


class BookingReadSerializer(serializers.ModelSerializer):
    """
    RU: Представление брони для владельца и арендатора.
    EN: Booking representation for both the landlord and the tenant.
    """

    listing_public_id = serializers.UUIDField(source="listing.public_id", read_only=True)
    tenant_email = serializers.EmailField(source="tenant.email", read_only=True)
    nights = serializers.SerializerMethodField()

    class Meta:
        model = Booking
        fields = (
            "public_id", "listing_public_id", "listing_title_snapshot",
            "tenant_email", "start_date", "end_date", "nights", "guests",
            "status", "price_per_night_snapshot", "total_price", "created_at",
        )

    @extend_schema_field(serializers.IntegerField())
    def get_nights(self, obj: Booking) -> int:
        """
        RU: Число ночей. Считается в Python из уже загруженных полей,
            дополнительного запроса не делает.
        EN: Number of nights. Computed in Python from already-loaded fields,
            so it costs no extra query.
        """
        return obj.nights


class BookingCreateSerializer(serializers.Serializer):
    """
    RU: Создание брони. Не ModelSerializer: снимки цены и заголовка
        считает сервис, клиент их передать не должен.
    EN: Booking creation. Not a ModelSerializer: the price and title snapshots
        are computed by the service and must not come from the client.
    """

    listing = serializers.SlugRelatedField(
        slug_field="public_id",
        queryset=Listing.objects.active(),
        help_text="public_id of the listing to book",
    )
    start_date = serializers.DateField(
        help_text="Check-in date, inclusive. Format YYYY-MM-DD",
    )
    end_date = serializers.DateField(
        help_text="Check-out date, exclusive: this night is not charged",
    )
    guests = serializers.IntegerField(
        min_value=1, default=1, help_text="Number of guests, at least 1",
    )

    def create(self, validated_data: dict) -> Booking:
        """
        RU: Делегирует сервису — там транзакция и select_for_update,
            защищающие от гонки за одни и те же даты.
        EN: Delegates to the service, where a transaction and select_for_update
            guard against a race for the same dates.
        """
        return create_booking(
            tenant=self.context["request"].user,
            listing_id=validated_data["listing"].pk,
            start_date=validated_data["start_date"],
            end_date=validated_data["end_date"],
            guests=validated_data["guests"],
        )


class BookingStatusSerializer(serializers.Serializer):
    """
    RU: Смена статуса через явное действие, а не через PATCH поля.
        Так право проверяется отдельно для каждого перехода.
    EN: Status change as an explicit action rather than a field PATCH,
        so each transition can be permission-checked separately.
    """

    status = serializers.ChoiceField(
        choices=BookingStatus.choices,
        help_text="Target status. Allowed transitions are defined by the state machine",
    )