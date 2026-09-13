from __future__ import annotations

from rest_framework import mixins, viewsets

from core.permissions import IsReviewAuthor
from .models import Review
from .serializers import ReviewCreateSerializer, ReviewReadSerializer


class ReviewViewSet(
    mixins.CreateModelMixin,
    mixins.RetrieveModelMixin,
    mixins.UpdateModelMixin,
    mixins.ListModelMixin,
    viewsets.GenericViewSet,
):
    """
    RU: Отзывы. DestroyModelMixin отсутствует намеренно: удаление отзыва
        доступно только админу через админку, и только мягкое.
    EN: Reviews. DestroyModelMixin is deliberately absent: deleting a review is
        a staff-only action through the admin, and soft only.
    """

    queryset = Review.objects.select_related("author", "listing", "booking")
    permission_classes = [IsReviewAuthor]

    def get_serializer_class(self):
        if self.action in ("create", "update", "partial_update"):
            return ReviewCreateSerializer
        return ReviewReadSerializer