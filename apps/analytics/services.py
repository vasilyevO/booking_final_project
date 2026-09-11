from __future__ import annotations

from django.db.models import F
from django.utils import timezone

from apps.listings.models import Listing
from .models import ListingView


def register_listing_view(*, listing_id: int, user=None, session_key: str = "") -> None:
    """
    RU: Фиксирует просмотр и увеличивает счётчик, если сегодня он ещё не был засчитан.
    EN: Records a view and increments the counter if it has not been counted today.
    """
    _view, created = ListingView.objects.get_or_create(
        listing_id=listing_id,
        user=user if user and user.is_authenticated else None,
        session_key=session_key,
        viewed_on=timezone.localdate(),
    )
    if not created:
        return

    # RU: атомарный инкремент — арифметика выполняется в БД, гонки исключены.
    #     update() сигналов не шлёт, поэтому историю объявления не засоряет.
    # EN: atomic increment — the arithmetic runs in the database, no race.
    #     update() fires no signals, so the listing history stays clean.
    Listing.objects.filter(pk=listing_id).update(views_count=F("views_count") + 1)