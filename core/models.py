from __future__ import annotations

import uuid

from django.db import models
from django.utils import timezone


class TimeStampedModel(models.Model):
    """
    Abstract base providing creation and update timestamps.
    """

    # default=timezone.now instead of auto_now_add keeps the field editable,
    # so it can be set in fixtures and tests.
    created_at = models.DateTimeField(default=timezone.now, editable=False, db_index=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        abstract = True


class PublicIdModel(models.Model):
    """
    Unguessable public identifier for URLs. The primary key stays a
    BigAutoField and is used for internal relations.
    """

    # unique already creates an index, so db_index would be redundant.
    public_id = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)

    class Meta:
        abstract = True


class SoftDeleteQuerySet(models.QuerySet):
    """
    QuerySet where bulk deletion is replaced by a soft-delete flag.
    """

    def alive(self) -> "SoftDeleteQuerySet":
        """
        Only records that are not soft-deleted.
        """
        return self.filter(deleted_at__isnull=True)

    def dead(self) -> "SoftDeleteQuerySet":
        """
        Only soft-deleted records.
        """
        return self.filter(deleted_at__isnull=False)

    def delete(self) -> int:
        """
        Marks records as deleted instead of a physical DELETE.
        NOTE: update() fires no signals, so bulk deletion is not
        captured by simple-history.
        """
        return self.update(deleted_at=timezone.now())


class SoftDeleteManager(models.Manager.from_queryset(SoftDeleteQuerySet)):
    """
    Default manager that hides soft-deleted records.
    """

    def get_queryset(self) -> SoftDeleteQuerySet:
        return super().get_queryset().filter(deleted_at__isnull=True)


class SoftDeleteModel(models.Model):
    """
    Abstract base with soft deletion: the row stays in the database.
    """

    deleted_at = models.DateTimeField(null=True, blank=True, editable=False, db_index=True)

    objects = SoftDeleteManager()
    all_objects = models.Manager()

    class Meta:
        abstract = True
        # Related objects are resolved via the base manager. Without this line
        # booking.listing fails once the listing is soft-deleted.
        base_manager_name = "all_objects"

    def delete(self, using: str | None = None, keep_parents: bool = False) -> None:
        """
        Marks the object as deleted. save() fires signals, so the
        deletion is captured by simple-history.
        """
        self.deleted_at = timezone.now()
        self.save(update_fields=["deleted_at", "updated_at"])

    def restore(self) -> None:
        """
        Clears the soft-delete flag.
        """
        self.deleted_at = None
        self.save(update_fields=["deleted_at", "updated_at"])

    @property
    def is_deleted(self) -> bool:
        """
        True if the object is soft-deleted.
        """
        return self.deleted_at is not None

class ValidatedModel(models.Model):
    """
    Runs full_clean() before saving. Django does not do this by itself:
    historically ModelForm handled validation, and DRF uses its own.
    """

    class Meta:
        abstract = True

    def save(self, *args, **kwargs):
        # escape hatch for data migrations and imports
        if kwargs.pop("skip_validation", False):
            return super().save(*args, **kwargs)

        update_fields = kwargs.get("update_fields")
        exclude = None
        if update_fields is not None:
            names = set(update_fields)
            # on a partial save validate only the written fields,
            # otherwise validate_unique() issues pointless queries
            exclude = [
                f.name
                for f in self._meta.concrete_fields
                if f.name not in names and f.attname not in names
            ]

        # exclude affects clean_fields() and validate_unique(),
        # but clean() always runs in full
        self.full_clean(exclude=exclude)
        return super().save(*args, **kwargs)