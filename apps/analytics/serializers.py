from __future__ import annotations

from rest_framework import serializers
from django.utils.translation import gettext_lazy as _


class PopularKeywordSerializer(serializers.Serializer):
    """
    An aggregate row: keyword and hit count. Not a ModelSerializer,
    since the source is values().annotate().
    """

    keyword = serializers.CharField(help_text=_("Normalised search keyword"))
    total = serializers.IntegerField(help_text=_("How many times it was searched"))


class PopularListingSerializer(serializers.Serializer):
    """
    A listing in the popularity ranking by view count.
    """

    public_id = serializers.UUIDField()
    title = serializers.CharField()
    views_count = serializers.IntegerField(help_text=_("Total de-duplicated views"))
