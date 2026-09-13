from __future__ import annotations

from django.db.models import F
from django.utils import timezone

from apps.listings.models import Listing
from .models import ListingView, ListingStats


def register_listing_view(*, listing_id: int, user=None, session_key: str = "") -> None:
    """
    RU: Фиксирует просмотр и увеличивает счётчик в отдельной таблице.
        Строка listings_listing при этом не трогается.
    EN: Records a view and bumps the counter in the separate stats table.
        The listings_listing row is never touched.
    """
    _view, created = ListingView.objects.get_or_create(
        listing_id=listing_id,
        user=user if user and user.is_authenticated else None,
        session_key=session_key,
        viewed_on=timezone.localdate(),
    )
    if not created:
        return

    ListingStats.objects.get_or_create(listing_id=listing_id)
    # RU: атомарный инкремент — арифметика выполняется в БД
    # EN: atomic increment — the arithmetic runs in the database
    ListingStats.objects.filter(listing_id=listing_id).update(
        views_count=F("views_count") + 1, last_viewed_at=timezone.now()
    )