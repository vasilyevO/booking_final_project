from __future__ import annotations

from rest_framework import mixins, viewsets
from rest_framework.permissions import IsAuthenticatedOrReadOnly

from core.permissions import IsReviewAuthor
from .models import Review
from .serializers import (
    ReviewCreateSerializer, ReviewReadSerializer, ReviewUpdateSerializer,
)


class ReviewViewSet(
    mixins.CreateModelMixin,
    mixins.RetrieveModelMixin,
    mixins.UpdateModelMixin,
    mixins.ListModelMixin,
    viewsets.GenericViewSet,
):
    """
    Reviews. DestroyModelMixin is deliberately absent: deleting a review is
    a staff-only action through the admin, and soft only.
    """

    queryset = Review.objects.select_related("author", "listing", "booking")
    # IsReviewAuthor is object-level only and never runs on create —
    # without IsAuthenticatedOrReadOnly an anonymous user could post.
    permission_classes = [IsAuthenticatedOrReadOnly, IsReviewAuthor]

    def get_serializer_class(self):
        if self.action == "create":
            return ReviewCreateSerializer
        if self.action in ("update", "partial_update"):
            return ReviewUpdateSerializer
        return ReviewReadSerializer