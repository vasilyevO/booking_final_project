from __future__ import annotations

import django_filters as filters
from django.utils.translation import gettext_lazy as _

from core.text import spelling_variants
from .models import Listing, PropertyType


class ListingFilter(filters.FilterSet):
    """
    Listing search filters. Parameter names match the OpenAPI schema.
    """

    city = filters.CharFilter(method="filter_city", label=_("City, any spelling"))
    price_min = filters.NumberFilter(
        field_name="price_base", lookup_expr="gte", label=_("Minimum price, EUR")
    )
    price_max = filters.NumberFilter(
        field_name="price_base", lookup_expr="lte", label=_("Maximum price, EUR")
    )
    rooms_min = filters.NumberFilter(field_name="rooms", lookup_expr="gte")
    rooms_max = filters.NumberFilter(field_name="rooms", lookup_expr="lte")
    property_type = filters.ChoiceFilter(
        choices=PropertyType.choices, label=_("Property type")
    )

    class Meta:
        model = Listing
        fields = ("city", "district", "property_type")

    def filter_city(self, queryset, name: str, value: str):
        """
        Match on the folded form: Köln and Koeln both produce koeln, and
        spelling_variants() adds koeln for an umlaut typed without its
        diacritic (koln).
        """
        return queryset.filter(city_normalized__in=spelling_variants(value))