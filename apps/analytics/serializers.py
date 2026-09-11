from __future__ import annotations

from rest_framework import serializers


class PopularKeywordSerializer(serializers.Serializer):
    """
    RU: Строка агрегата: ключевое слово и число обращений.
        Не ModelSerializer — источником служит values().annotate().
    EN: An aggregate row: keyword and hit count. Not a ModelSerializer,
        since the source is values().annotate().
    """

    keyword = serializers.CharField(help_text="Normalised search keyword")
    total = serializers.IntegerField(help_text="How many times it was searched")


class PopularListingSerializer(serializers.Serializer):
    """
    RU: Объявление в рейтинге популярности по числу просмотров.
    EN: A listing in the popularity ranking by view count.
    """

    public_id = serializers.UUIDField()
    title = serializers.CharField()
    views_count = serializers.IntegerField(help_text="Total de-duplicated views")
