from __future__ import annotations

from rest_framework import serializers

from apps.bookings.models import Booking
from .models import Review
from django.utils.translation import gettext_lazy as _


class ReviewReadSerializer(serializers.ModelSerializer):
    """
    RU: Отзыв в списке объявления.
    EN: A review as shown on a listing.
    """

    author_email = serializers.EmailField(source="author.email", read_only=True)

    class Meta:
        model = Review
        fields = ("id", "author_email", "rating", "text", "created_at")


class ReviewCreateSerializer(serializers.ModelSerializer):
    """
    RU: Создание отзыва. Объявление и автор берутся из брони, поэтому
        в запросе их нет.
    EN: Review creation. The listing and the author are derived from the
        booking, so they are absent from the request.
    """

    booking = serializers.SlugRelatedField(
        slug_field="public_id",
        queryset=Booking.objects.all(),
        help_text=_("public_id of the completed booking being reviewed"),
    )

    class Meta:
        model = Review
        fields = ("id", "booking", "rating", "text")
        read_only_fields = ("id",)

    def validate_booking(self, booking: Booking) -> Booking:
        """
        RU: Проверка принадлежности — это право доступа, а не инвариант данных,
            поэтому она живёт здесь, а не в Review.clean().
        EN: Ownership is an access rule rather than a data invariant, so it
            belongs here and not in Review.clean().
        """
        if booking.tenant_id != self.context["request"].user.pk:
            raise serializers.ValidationError(_("You can only review your own stay"))
        if hasattr(booking, "review"):
            raise serializers.ValidationError(_("This booking already has a review"))
        return booking

    # RU: «бронь завершена» и «проживание закончилось» проверяет Review.clean()
    #     через full_clean() в ValidatedModel.save() — здесь не дублируем.
    # EN: "booking completed" and "stay finished" are checked by Review.clean()
    #     via full_clean() in ValidatedModel.save() — not duplicated here.