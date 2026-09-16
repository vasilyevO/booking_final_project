from __future__ import annotations

from rest_framework import mixins, viewsets
from rest_framework.permissions import IsAuthenticatedOrReadOnly

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
    # RU: IsReviewAuthor проверяет только объект и на create не вызывается —
    #     без IsAuthenticatedOrReadOnly отзыв мог отправить аноним.
    # EN: IsReviewAuthor is object-level only and never runs on create —
    #     without IsAuthenticatedOrReadOnly an anonymous user could post.
    permission_classes = [IsAuthenticatedOrReadOnly, IsReviewAuthor]

    def get_serializer_class(self):
        if self.action in ("create", "update", "partial_update"):
            return ReviewCreateSerializer
        return ReviewReadSerializer