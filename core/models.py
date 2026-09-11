from __future__ import annotations

import uuid

from django.db import models
from django.utils import timezone


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
    RU: Непредсказуемый публичный идентификатор для URL. Первичный ключ
        остаётся BigAutoField и используется во внутренних связях.
    EN: Unguessable public identifier for URLs. The primary key stays a
        BigAutoField and is used for internal relations.
    """

    # RU: unique уже создаёт индекс — db_index указывать не нужно.
    # EN: unique already creates an index, so db_index would be redundant.
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
            ВНИМАНИЕ: update() не вызывает сигналы, поэтому в историю
            simple-history массовое удаление не попадёт.
        EN: Marks records as deleted instead of a physical DELETE.
            NOTE: update() fires no signals, so bulk deletion is not
            captured by simple-history.
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
        RU: Помечает объект удалённым. save() вызывает сигналы, поэтому
            удаление попадает в историю simple-history.
        EN: Marks the object as deleted. save() fires signals, so the
            deletion is captured by simple-history.
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

class ValidatedModel(models.Model):
    """
    RU: Вызывает full_clean() перед сохранением. Django сам этого не делает:
        исторически валидацию выполняла ModelForm, а DRF использует свою.
    EN: Runs full_clean() before saving. Django does not do this by itself:
        historically ModelForm handled validation, and DRF uses its own.
    """

    class Meta:
        abstract = True

    def save(self, *args, **kwargs):
        # RU: аварийный обход для миграций данных и импорта
        # EN: escape hatch for data migrations and imports
        if kwargs.pop("skip_validation", False):
            return super().save(*args, **kwargs)

        update_fields = kwargs.get("update_fields")
        exclude = None
        if update_fields is not None:
            names = set(update_fields)
            # RU: при частичном сохранении проверяем только изменённые поля,
            #     иначе validate_unique() сделает лишние запросы
            # EN: on a partial save validate only the written fields,
            #     otherwise validate_unique() issues pointless queries
            exclude = [
                f.name
                for f in self._meta.concrete_fields
                if f.name not in names and f.attname not in names
            ]

        # RU: exclude влияет на clean_fields() и validate_unique(),
        #     но clean() выполняется целиком в любом случае
        # EN: exclude affects clean_fields() and validate_unique(),
        #     but clean() always runs in full
        self.full_clean(exclude=exclude)
        return super().save(*args, **kwargs)