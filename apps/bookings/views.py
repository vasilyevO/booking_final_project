from __future__ import annotations

from django.core.exceptions import ValidationError
from django.db.models import Q
from drf_spectacular.utils import extend_schema, extend_schema_view
from rest_framework import mixins, status, viewsets
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from core.permissions import IsBookingParticipant, IsListingOwner
from .models import Booking, BookingStatus
from .serializers import BookingCreateSerializer, BookingReadSerializer
from .services import change_status
from django.utils.translation import gettext_lazy as _


@extend_schema_view(
    list=extend_schema(summary=_("My bookings, as a tenant or as a landlord")),
    create=extend_schema(summary=_("Create a booking")),
)
class BookingViewSet(
    mixins.CreateModelMixin,
    mixins.RetrieveModelMixin,
    mixins.ListModelMixin,
    viewsets.GenericViewSet,
):
    """
    RU: Бронирования. Полного update нет намеренно: статус меняется только
        явными действиями, каждое со своей проверкой прав.
    EN: Bookings. There is deliberately no full update: the status changes only
        through explicit actions, each with its own permission check.
    """

    lookup_field = "public_id"
    # RU: IsAuthenticated обязателен явно: permission_classes перекрывает
    #     DEFAULT_PERMISSION_CLASSES целиком, а IsBookingParticipant проверяет
    #     только объект. Без него анонимный GET доходил до get_queryset,
    #     где filter(tenant=AnonymousUser) падал с 500 вместо 401.
    # EN: IsAuthenticated must be listed explicitly: permission_classes replaces
    #     DEFAULT_PERMISSION_CLASSES entirely, and IsBookingParticipant only
    #     checks the object. Without it an anonymous GET reached get_queryset,
    #     where filter(tenant=AnonymousUser) raised a 500 instead of a 401.
    permission_classes = [IsAuthenticated, IsBookingParticipant]

    def get_queryset(self):
        """
        RU: Арендатор видит свои брони, владелец — брони на своё жильё,
            админ — все. Фильтрация в queryset, а не только в permission:
            иначе список отдал бы чужие записи.
        EN: A tenant sees their own bookings, an owner sees bookings on their
            properties, staff see everything. Filtering happens in the queryset,
            not only in the permission: otherwise the list would leak.
        """
        queryset = Booking.objects.select_related("listing", "tenant")
        user = self.request.user
        # RU: drf-spectacular инстанцирует вьюсет без запроса — фильтр по
        #     AnonymousUser упал бы на генерации схемы.
        # EN: drf-spectacular instantiates the viewset without a request — a
        #     filter on AnonymousUser would break schema generation.
        if getattr(self, "swagger_fake_view", False) or not user.is_authenticated:
            return queryset.none()
        if user.is_staff:
            return queryset
        return queryset.filter(Q(tenant=user) | Q(listing__owner=user))

    def get_serializer_class(self):
        return BookingCreateSerializer if self.action == "create" else BookingReadSerializer

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        booking = serializer.save()
        return Response(
            BookingReadSerializer(booking).data, status=status.HTTP_201_CREATED
        )

    def _transition(self, request, target: str, permission) -> Response:
        """
        RU: Общая обёртка перехода: проверка права, вызов сервиса, ответ.
            Три экшена отличаются только целевым статусом и правом.
        EN: Shared transition wrapper: permission check, service call, response.
            The three actions differ only in target status and permission.
        """
        booking = self.get_object()
        permission().has_object_permission(request, self, booking) or self.permission_denied(
            request, message=permission.message
        )
        try:
            change_status(booking, target)
        except ValidationError as exc:
            return Response({"detail": exc.messages}, status=status.HTTP_400_BAD_REQUEST)
        return Response(BookingReadSerializer(booking).data)

    @extend_schema(summary=_("Confirm a booking (landlord only)"), request=None)
    @action(detail=True, methods=["post"])
    def confirm(self, request, public_id=None):
        return self._transition(request, BookingStatus.CONFIRMED, IsListingOwner)

    @extend_schema(summary=_("Reject a booking (landlord only)"), request=None)
    @action(detail=True, methods=["post"])
    def reject(self, request, public_id=None):
        return self._transition(request, BookingStatus.REJECTED, IsListingOwner)

    @extend_schema(summary=_("Cancel a booking (tenant or landlord)"), request=None)
    @action(detail=True, methods=["post"])
    def cancel(self, request, public_id=None):
        """
        RU: Отменить может любой участник. Срок отмены проверяет модель.
        EN: Either participant may cancel. The deadline is checked by the model.
        """
        booking = self.get_object()
        if not booking.is_cancellable():
            return Response(
                {"detail": _("The free cancellation deadline has passed.")},
                status=status.HTTP_400_BAD_REQUEST,
            )
        return self._transition(request, BookingStatus.CANCELLED, IsBookingParticipant)