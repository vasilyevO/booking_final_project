from __future__ import annotations

import django_filters as filters

from core.text import normalize_search_text
from .models import Listing, PropertyType


class ListingFilter(filters.FilterSet):
    """
    RU: Фильтры из ТЗ. Имена параметров совпадают с тем, что видно в Swagger.
    EN: The filters required by the brief. Parameter names match what Swagger shows.
    """

    city = filters.CharFilter(method="filter_city", label="City, any spelling")
    price_min = filters.NumberFilter(field_name="price_per_night", lookup_expr="gte")
    price_max = filters.NumberFilter(field_name="price_per_night", lookup_expr="lte")
    rooms_min = filters.NumberFilter(field_name="rooms", lookup_expr="gte")
    rooms_max = filters.NumberFilter(field_name="rooms", lookup_expr="lte")
    property_type = filters.ChoiceFilter(choices=PropertyType.choices)

    class Meta:
        model = Listing
        fields = ("city", "district", "property_type")

    def filter_city(self, queryset, name: str, value: str):
        """
        RU: Ищем по свёрнутой форме: Köln, Koeln и koln дают один и тот же
            ключ koeln и находят одно и то же.
        EN: Match on the folded form: Köln, Koeln and koln all produce the same
            key koeln and return the same results.
        """
        return queryset.filter(city_normalized=normalize_search_text(value))