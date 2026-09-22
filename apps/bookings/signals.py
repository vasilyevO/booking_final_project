from __future__ import annotations

from django.db import transaction
from django.db.models.signals import post_save
from django.dispatch import receiver

from .models import Booking
from .notifications import send_booking_created_emails, send_booking_status_email


@receiver(post_save, sender=Booking, dispatch_uid="booking_created_email")
def notify_on_booking_created(sender, instance: Booking, created: bool, **kwargs):
    """
    Emails to both parties when a booking is created.
    """
    if not created:
        return

    # post_save fires inside the transaction.atomic of create_booking().
    # Without on_commit the email is sent even if the transaction rolls
    # back: no booking in the database, yet the tenant already has the
    # email. It cannot be recalled.
    transaction.on_commit(lambda: send_booking_created_emails(instance.pk))


@receiver(post_save, sender=Booking, dispatch_uid="booking_status_email")
def notify_on_status_change(sender, instance: Booking, created: bool, **kwargs):
    """
    An email to the tenant when the status changes.
    """
    if created:
        return

    # Booking.save() assigns _original_status after super().save(), while
    # post_save is emitted inside it — so here the attribute still holds the
    # previous status. The transition is visible without pre_save and
    # without an extra database query.
    old_status = getattr(instance, "_original_status", None)
    if not old_status or old_status == instance.status:
        return

    transaction.on_commit(
        lambda: send_booking_status_email(instance.pk, old_status)
    )