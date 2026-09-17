from __future__ import annotations

from django.db.models import Count
from drf_spectacular.utils import extend_schema
from rest_framework import viewsets
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from apps.listings.models import Listing
from .models import ListingStats, SearchQuery
from .serializers import PopularKeywordSerializer, PopularListingSerializer
from django.utils.translation import gettext_lazy as _


class AnalyticsViewSet(viewsets.GenericViewSet):
    """
    RU: Аналитика только на чтение. GenericViewSet без миксинов: CRUD здесь
        не нужен, есть только два агрегирующих эндпоинта.
    EN: Read-only analytics. A GenericViewSet with no mixins: CRUD is not
        needed here, only two aggregate endpoints.
    """

    permission_classes = [IsAuthenticated]

    @extend_schema(summary=_("Most searched keywords"), responses=PopularKeywordSerializer)
    @action(detail=False, methods=["get"], url_path="popular-keywords")
    def popular_keywords(self, request):
        """
        RU: Топ ключевых слов. values().annotate() группирует в БД —
            это GROUP BY, а не подсчёт в Python.
        EN: Top keywords. values().annotate() groups in the database —
            a GROUP BY, not counting in Python.
        """
        queryset = (
            SearchQuery.objects.values("keyword")
            .annotate(total=Count("id"))
            .order_by("-total")[:20]
        )
        return Response(PopularKeywordSerializer(queryset, many=True).data)

    @extend_schema(summary=_("Most viewed listings"), responses=PopularListingSerializer)
    @action(detail=False, methods=["get"], url_path="popular-listings")
    def popular_listings(self, request):
        """
        RU: Объявления по числу просмотров. Владелец видит свои, админ — все.
        EN: Listings by view count. An owner sees their own, staff see all.
        """
        stats = ListingStats.objects.select_related("listing").order_by("-views_count")
        if not request.user.is_staff:
            stats = stats.filter(listing__owner=request.user)

        data = [
            {
                "public_id": row.listing.public_id,
                "title": row.listing.title,
                "views_count": row.views_count,
            }
            for row in stats[:20]
        ]
        return Response(PopularListingSerializer(data, many=True).data)