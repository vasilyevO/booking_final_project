from __future__ import annotations

from django.db import models
from django.utils import timezone
import uuid


class TimeStampedModel(models.Model):
    """
    RU: Абстрактная база с метками времени создания и обновления.
    EN: Abstract base providing creation and update timestamps.
    """

    # RU: default=timezone.now вместо auto_now_add — поле остаётся editable,
    #     значит его можно задать в фикстурах и тестах.
    # EN: default=timezone.now instead of auto_now_add keeps the field editable,
    #     so it can be set in fixtures and tests.
    created_at = models.DateTimeField(default=timezone.now, editable=False, db_index=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        abstract = True

class PublicIdModel(models.Model):
    """
    RU: Добавляет непредсказуемый публичный идентификатор для URL,
        не трогая первичный ключ.
    EN: Adds an unguessable public identifier for URLs without
        touching the primary key.
    """

    public_id = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)

    class Meta:
        abstract = True


class SoftDeleteQuerySet(models.QuerySet):
    """
    RU: QuerySet, в котором массовое удаление заменено на пометку удаления.
    EN: QuerySet where bulk deletion is replaced by a soft-delete flag.
    """

    def alive(self) -> "SoftDeleteQuerySet":
        """
        RU: Только неудалённые записи.
        EN: Only records that are not soft-deleted.
        """
        return self.filter(deleted_at__isnull=True)

    def dead(self) -> "SoftDeleteQuerySet":
        """
        RU: Только помеченные удалёнными записи.
        EN: Only soft-deleted records.
        """
        return self.filter(deleted_at__isnull=False)

    def delete(self) -> int:
        """
        RU: Помечает записи удалёнными вместо физического DELETE.
        EN: Marks records as deleted instead of issuing a physical DELETE.
        """
        return self.update(deleted_at=timezone.now())


class SoftDeleteManager(models.Manager.from_queryset(SoftDeleteQuerySet)):
    """
    RU: Менеджер по умолчанию, скрывающий удалённые записи.
    EN: Default manager that hides soft-deleted records.
    """

    def get_queryset(self) -> SoftDeleteQuerySet:
        return super().get_queryset().filter(deleted_at__isnull=True)


class SoftDeleteModel(models.Model):
    """
    RU: Абстрактная база с мягким удалением: строка остаётся в БД.
    EN: Abstract base with soft deletion: the row stays in the database.
    """

    deleted_at = models.DateTimeField(null=True, blank=True, editable=False, db_index=True)

    objects = SoftDeleteManager()
    all_objects = models.Manager()

    class Meta:
        abstract = True
        # RU: Связанные объекты резолвятся через base manager. Без этой строки
        #     booking.listing упадёт, если объявление помечено удалённым.
        # EN: Related objects are resolved via the base manager. Without this line
        #     booking.listing fails once the listing is soft-deleted.
        base_manager_name = "all_objects"

    def delete(self, using: str | None = None, keep_parents: bool = False) -> None:
        """
        RU: Помечает объект удалённым, не трогая строку в БД.
        EN: Marks the object as deleted without removing the database row.
        """
        self.deleted_at = timezone.now()
        self.save(update_fields=["deleted_at", "updated_at"])

    def restore(self) -> None:
        """
        RU: Снимает пометку удаления.
        EN: Clears the soft-delete flag.
        """
        self.deleted_at = None
        self.save(update_fields=["deleted_at", "updated_at"])

    @property
    def is_deleted(self) -> bool:
        """
        RU: True, если объект помечен удалённым.
        EN: True if the object is soft-deleted.
        """
        return self.deleted_at is not None