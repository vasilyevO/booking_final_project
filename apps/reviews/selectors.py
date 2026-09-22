# apps/reviews/selectors.py
from __future__ import annotations

from django.db.models import Avg, Count

from .models import Review


def owner_rating(user) -> dict:
    """
    Owner's average rating across all their listings, deleted ones included.
    Closes the loophole of recreating a listing to reset the reputation.
    """
    # all_objects rather than objects — otherwise soft-deleted rows drop out
    return Review.all_objects.filter(listing__owner=user).aggregate(
        avg=Avg("rating"), total=Count("id")
    )