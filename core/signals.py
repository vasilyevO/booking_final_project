from __future__ import annotations

import logging

from django.db.models.signals import post_delete, post_save
from django.dispatch import receiver

logger = logging.getLogger("core.db")

# RU: служебные модели исключаем, иначе лог утонет в сессиях и правах
# EN: service models are excluded, otherwise the log drowns in sessions and perms
EXCLUDED_LABELS = {
    "sessions.session",
    "admin.logentry",
    "contenttypes.contenttype",
    "auth.permission",
}

# RU: приложения, пишущие слишком часто, чтобы логировать каждую строку
# EN: apps writing too often for per-row logging
EXCLUDED_APPS = {"analytics"}


def _skip(sender) -> bool:
    """
    RU: Таблицы simple-history исключаем отдельно: каждая запись в них —
        следствие уже залогированной записи в основную таблицу, и без фильтра
        каждое изменение попадало бы в лог дважды.
    EN: simple-history tables are excluded separately: every row there follows a
        write to the main table that is already logged, and without the filter
        each change would appear twice.
    """
    if sender.__name__.startswith("Historical"):
        return True
    meta = sender._meta
    return meta.label_lower in EXCLUDED_LABELS or meta.app_label in EXCLUDED_APPS


@receiver(post_save, dispatch_uid="core_log_db_write")
def log_db_write(sender, instance, created: bool, raw: bool = False, **kwargs):
    """
    RU: Логирует создание и изменение любой доменной модели.
        raw=True означает загрузку фикстур — их логировать незачем.
        Приёмник без sender= ловит ВСЕ модели, поэтому фильтр обязателен.
    EN: Logs creation and updates of any domain model.
        raw=True means fixtures are being loaded — no point logging those.
        A receiver without sender= catches EVERY model, so the filter is a must.
    """
    if raw or _skip(sender):
        return

    update_fields = kwargs.get("update_fields")
    fields = ",".join(sorted(update_fields)) if update_fields else "all"
    logger.info(
        "%s %s pk=%s fields=%s",
        "create" if created else "update",
        sender._meta.label,
        instance.pk,
        fields,
    )


@receiver(post_delete, dispatch_uid="core_log_db_delete")
def log_db_delete(sender, instance, **kwargs):
    """
    RU: Физическое удаление. Мягкое удаление сюда не попадает — оно идёт
        через save(update_fields=["deleted_at"]) и логируется как update.
    EN: A physical delete. Soft deletion does not reach this receiver — it goes
        through save(update_fields=["deleted_at"]) and is logged as an update.
    """
    if _skip(sender):
        return
    logger.warning("delete %s pk=%s", sender._meta.label, instance.pk)