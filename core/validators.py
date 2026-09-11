from __future__ import annotations

from django.core.exceptions import ValidationError


def validate_not_own_listing(listing, tenant) -> None:
    """
    RU: Запрещает владельцу бронировать собственное жильё. Правило сравнивает
        колонки двух таблиц, поэтому CheckConstraint здесь неприменим.
    EN: Forbids an owner from booking their own property. The rule compares
        columns of two tables, so a CheckConstraint cannot express it.
    """
    if listing is None or tenant is None:
        return
    if listing.owner_id == tenant.pk:
        raise ValidationError("Владелец не может забронировать собственное жильё.")