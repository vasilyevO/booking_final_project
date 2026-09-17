from __future__ import annotations

from django.db.models import Avg, Count, Q
from django.utils.functional import lazy
from drf_spectacular.utils import OpenApiParameter, extend_schema, extend_schema_view
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.parsers import FormParser, MultiPartParser
from rest_framework.permissions import AllowAny
from rest_framework.response import Response

from apps.analytics.services import register_listing_view
from apps.analytics.models import SearchQuery
from apps.bookings.models import BookingStatus
from apps.reviews.models import Review
from apps.reviews.serializers import ReviewReadSerializer
from core.text import normalize_search_text
from core.permissions import IsOwnerOrReadOnly, ReadOnlyOrModelPermission
from .filters import ListingFilter
from .models import Listing, ListingPhoto
from .serializers import (
    ListingDetailSerializer, ListingListSerializer, ListingPhotoSerializer,
    ListingWriteSerializer, PhotoReorderSerializer,
)
from .services import reorder_photos
from django.utils.translation import gettext_lazy as _


@extend_schema_view(
    list=extend_schema(
        summary=_("Search and filter listings"),
        parameters=[
            OpenApiParameter("search", str, description=_("Free-text search in title and description")),
            OpenApiParameter("city", str, description=_("City in any spelling: Köln, Koeln, koln")),
            OpenApiParameter("price_min", float, description=_("Minimum price per night, EUR")),
            OpenApiParameter("price_max", float, description=_("Maximum price per night, EUR")),
            OpenApiParameter(
                "ordering", str,
                # RU: % у lazy-строки вычисляется сразу, при импорте, и фиксирует
                #     язык по умолчанию. lazy() откладывает подстановку до рендера.
                # EN: % on a lazy string is evaluated at import time and freezes
                #     the default language. lazy() defers the substitution to render.
                description=lazy(
                    lambda: _("Sort order. Available fields: %(fields)s") % {
                        "fields": "price_base, created_at, stats__views_count"
                    },
                    str,
                )(),
            ),
        ],
    ),
    retrieve=extend_schema(summary=_("Listing details")),
)
class ListingViewSet(viewsets.ModelViewSet):
    """
    RU: Объявления. Чтение открыто анонимам, создание требует группы
        landlords, редактирование — владения объектом.
    EN: Listings. Reading is open to anonymous users, creating requires the
        landlords group, editing requires object ownership.
    """

    # RU: public_id вместо pk — порядковые номера наружу не отдаём
    # EN: public_id instead of pk — never expose sequential identifiers
    lookup_field = "public_id"
    filterset_class = ListingFilter
    ordering_fields = ("price_base", "created_at", "stats__views_count")
    ordering = ("-created_at", "-id")
    permission_classes = [ReadOnlyOrModelPermission, IsOwnerOrReadOnly]

    def get_queryset(self):
        """
        RU: Рейтинг и число отзывов считаются одним запросом через annotate.
            filter= внутри агрегата компилируется в COUNT(CASE WHEN ...) и
            лишнего запроса не создаёт.
        EN: Rating and review count come from a single annotated query.
            filter= inside the aggregate compiles to COUNT(CASE WHEN ...) and
            costs no extra query.
        """
        completed = Q(
            reviews__booking__status=BookingStatus.COMPLETED,
            reviews__deleted_at__isnull=True,
        )
        queryset = Listing.objects.with_related().annotate(
            rating=Avg("reviews__rating", filter=completed),
            reviews_count=Count("reviews", filter=completed),
        )
        # RU: чужие неактивные объявления в выдаче не показываем
        # EN: other people's inactive listings stay out of the results
        user = self.request.user
        if user.is_authenticated and not user.is_staff:
            return queryset.filter(Q(is_active=True) | Q(owner=user))
        if user.is_staff:
            return queryset
        return queryset.active()

    def filter_queryset(self, queryset):
        """
        RU: Свободный поиск идёт через ListingQuerySet.search() — FULLTEXT
            с сортировкой по релевантности. SearchFilter из DRF здесь не
            работал: он опирается на search_fields и строит LIKE.
        EN: Free-text search goes through ListingQuerySet.search() — FULLTEXT
            ordered by relevance. The DRF SearchFilter did nothing here: it
            relies on search_fields and builds a LIKE.
        """
        queryset = super().filter_queryset(queryset)
        term = self.request.query_params.get("search", "").strip()
        if term:
            queryset = queryset.search(term)
        return queryset

    def list(self, request, *args, **kwargs):
        """
        RU: Поисковый запрос попадает в аналитику — без этой записи
            эндпоинт popular-keywords всегда отдавал пустой список.
        EN: The search term is recorded for analytics — without this write the
            popular-keywords endpoint always returned an empty list.
        """
        response = super().list(request, *args, **kwargs)
        term = request.query_params.get("search", "").strip()
        if term:
            SearchQuery.objects.create(
                user=request.user if request.user.is_authenticated else None,
                keyword=normalize_search_text(term),
                results_count=response.data.get("count", 0),
            )
        return response

    def get_serializer_class(self):
        if self.action in ("create", "update", "partial_update"):
            return ListingWriteSerializer
        if self.action == "retrieve":
            return ListingDetailSerializer
        return ListingListSerializer

    def get_permissions(self):
        if self.action in ("list", "retrieve", "reviews"):
            return [AllowAny()]
        return super().get_permissions()

    def retrieve(self, request, *args, **kwargs):
        """
        RU: Просмотр фиксируется в analytics и не трогает строку объявления.
        EN: The view is recorded in analytics and never touches the listing row.
        """
        listing = self.get_object()
        serializer = self.get_serializer(listing)
        response = Response(serializer.data)
        register_listing_view(
            listing_id=listing.pk,
            user=request.user,
            session_key=request.session.session_key or "",
        )
        return response

    def perform_destroy(self, instance):
        """
        RU: Мягкое удаление: SoftDeleteModel.delete() ставит deleted_at.
            Строка остаётся, отзывы и брони сохраняют ссылку на неё.
        EN: Soft deletion: SoftDeleteModel.delete() sets deleted_at. The row
            stays, and reviews and bookings keep referencing it.
        """
        instance.delete()

    @extend_schema(summary=_("Upload a photo"), request=ListingPhotoSerializer)
    @action(detail=True, methods=["post"], parser_classes=[MultiPartParser, FormParser])
    def photos(self, request, public_id=None):
        """
        RU: Загрузка фото. Позиция по умолчанию — в конец списка.
        EN: Photo upload. The default position appends to the end of the list.
        """
        listing = self.get_object()
        self.check_object_permissions(request, listing)
        serializer = ListingPhotoSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        last = listing.photos.order_by("-position").first()
        serializer.save(listing=listing, position=(last.position + 10) if last else 10)
        return Response(serializer.data, status=status.HTTP_201_CREATED)

    @extend_schema(summary=_("Reorder photos"), request=PhotoReorderSerializer)
    @action(detail=True, methods=["post"], url_path="photos/reorder")
    def reorder(self, request, public_id=None):
        """
        RU: Перестановка фото целиком, одной транзакцией.
        EN: Reorders all photos at once, in a single transaction.
        """
        listing = self.get_object()
        self.check_object_permissions(request, listing)
        serializer = PhotoReorderSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        reorder_photos(listing=listing, photo_ids=serializer.validated_data["photo_ids"])
        return Response(ListingPhotoSerializer(listing.photos.all(), many=True).data)

    @extend_schema(summary=_("Reviews of this listing"), responses=ReviewReadSerializer)
    @action(detail=True, methods=["get"])
    def reviews(self, request, public_id=None):
        """
        RU: Отзывы объявления. Открыто всем, мягко удалённые скрыты.
        EN: Reviews of the listing. Public, soft-deleted ones are hidden.
        """
        listing = self.get_object()
        queryset = Review.objects.filter(listing=listing).select_related("author")
        page = self.paginate_queryset(queryset)
        serializer = ReviewReadSerializer(page, many=True)
        return self.get_paginated_response(serializer.data)