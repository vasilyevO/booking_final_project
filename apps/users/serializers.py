from __future__ import annotations

from django.contrib.auth.models import Group
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError as DjangoValidationError
from django.db import transaction
from rest_framework import serializers

from .models import User
from django.utils.translation import gettext_lazy as _


class UserSerializer(serializers.ModelSerializer):
    """
    Public representation of a user.
    """

    groups = serializers.SlugRelatedField(
        many=True, read_only=True, slug_field="name",
        help_text=_("Role groups the user belongs to"),
    )

    class Meta:
        model = User
        # only public_id is exposed; the internal id stays private
        fields = ("public_id", "email", "first_name", "last_name", "phone", "groups")
        read_only_fields = ("public_id", "email", "groups")


class RegisterSerializer(serializers.ModelSerializer):
    """
    Registration. The role is a serializer field, not a model field:
    Django groups remain the single source of truth.
    """

    password = serializers.CharField(
        write_only=True, style={"input_type": "password"},
        help_text=_("At least 8 characters, not entirely numeric"),
    )
    password_confirm = serializers.CharField(
        write_only=True, style={"input_type": "password"},
        help_text=_("Repeat the password exactly"),
    )
    group = serializers.ChoiceField(
        choices=("tenants", "landlords"),
        write_only=True,
        help_text=_("tenants may book and review, landlords may publish listings"),
    )

    class Meta:
        model = User
        fields = (
            "public_id", "email", "first_name", "last_name", "phone",
            "password", "password_confirm", "group",
        )
        read_only_fields = ("public_id",)

    def validate_password(self, value: str) -> str:
        """
        Run the password through AUTH_PASSWORD_VALIDATORS from settings.
        """
        try:
            validate_password(value)
        except DjangoValidationError as exc:
            raise serializers.ValidationError(list(exc.messages)) from exc
        return value

    def validate(self, attrs: dict) -> dict:
        """
        Cross-field check: the two passwords must match.
        """
        if attrs["password"] != attrs["password_confirm"]:
            raise serializers.ValidationError({"password_confirm": _("Passwords do not match")})
        return attrs

    @transaction.atomic
    def create(self, validated_data: dict) -> User:
        """
        Creates the user and adds them to the chosen group in one transaction.
        """
        validated_data.pop("password_confirm")
        group_name = validated_data.pop("group")
        password = validated_data.pop("password")

        user = User.objects.create_user(password=password, **validated_data)
        user.groups.add(Group.objects.get(name=group_name))
        return user