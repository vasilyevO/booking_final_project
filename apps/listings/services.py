from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils.translation import gettext_lazy as _

from .models import ListingPhoto

# step of 10 — inserting between neighbours needs no full reindex
POSITION_STEP = 10


@transaction.atomic
def reorder_photos(*, listing, photo_ids: list[int]) -> None:
    """
    Reorders photos according to the given list of ids. One transaction —
    either the whole new order applies, or nothing does.
    """
    photos = {p.pk: p for p in listing.photos.select_for_update()}
    if set(photos) != set(photo_ids):
        raise ValidationError(_("Photo list does not match the listing"))

    for index, photo_id in enumerate(photo_ids, start=1):
        photos[photo_id].position = index * POSITION_STEP

    ListingPhoto.objects.bulk_update(photos.values(), ["position"])