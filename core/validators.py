from __future__ import annotations

from django.core.exceptions import ValidationError
from django.utils.translation import gettext_lazy as _


def validate_not_own_listing(listing, tenant) -> None:
    """
    Forbids an owner from booking their own property. The rule compares
    columns of two tables, so a CheckConstraint cannot express it.
    """
    if listing is None or tenant is None:
        return
    if listing.owner_id == tenant.pk:
        raise ValidationError(
            _("You cannot book your own property."),
            code="own_listing",
        )