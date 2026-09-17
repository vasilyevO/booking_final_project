from __future__ import annotations

from django.db import transaction
from django.db.models.signals import post_save
from django.dispatch import receiver

from .models import Booking
from .notifications import send_booking_created_emails, send_booking_status_email


@receiver(post_save, sender=Booking, dispatch_uid="booking_created_email")
def notify_on_booking_created(sender, instance: Booking, created: bool, **kwargs):
    """
    RU: Письмо обеим сторонам при создании брони.
    EN: Emails to both parties when a booking is created.
    """
    if not created:
        return

    # RU: post_save срабатывает ВНУТРИ transaction.atomic из create_booking().
    #     Без on_commit письмо уйдёт даже при откате транзакции: брони в базе
    #     не будет, а арендатор её уже получит. Отозвать письмо нельзя.
    # EN: post_save fires INSIDE the transaction.atomic of create_booking().
    #     Without on_commit the email is sent even if the transaction rolls
    #     back: no booking in the database, yet the tenant already has the
    #     email. It cannot be recalled.
    transaction.on_commit(lambda: send_booking_created_emails(instance.pk))


@receiver(post_save, sender=Booking, dispatch_uid="booking_status_email")
def notify_on_status_change(sender, instance: Booking, created: bool, **kwargs):
    """
    RU: Письмо арендатору при смене статуса.
    EN: An email to the tenant when the status changes.
    """
    if created:
        return

    # RU: Booking.save() присваивает _original_status ПОСЛЕ super().save(),
    #     а post_save отправляется ВНУТРИ него — значит здесь атрибут ещё
    #     хранит прежний статус. Переход виден без pre_save и без
    #     дополнительного запроса к БД.
    # EN: Booking.save() assigns _original_status AFTER super().save(), while
    #     post_save is emitted INSIDE it — so here the attribute still holds the
    #     previous status. The transition is visible without pre_save and
    #     without an extra database query.
    old_status = getattr(instance, "_original_status", None)
    if not old_status or old_status == instance.status:
        return

    transaction.on_commit(
        lambda: send_booking_status_email(instance.pk, old_status)
    )