from django.core.exceptions import ValidationError
from django.db import transaction

from .models import ListingPhoto

# RU: шаг 10 — вставка между соседями не требует переиндексации всего списка
# EN: step of 10 — inserting between neighbours needs no full reindex
POSITION_STEP = 10


@transaction.atomic
def reorder_photos(*, listing, photo_ids: list[int]) -> None:
    """
    RU: Переставляет фото по переданному списку id. Одна транзакция —
        применяется либо весь новый порядок, либо ничего.
    EN: Reorders photos according to the given list of ids. One transaction —
        either the whole new order applies, or nothing does.
    """
    photos = {p.pk: p for p in listing.photos.select_for_update()}
    if set(photos) != set(photo_ids):
        raise ValidationError("Photo list does not match the listing")

    for index, photo_id in enumerate(photo_ids, start=1):
        photos[photo_id].position = index * POSITION_STEP

    ListingPhoto.objects.bulk_update(photos.values(), ["position"])