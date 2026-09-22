from __future__ import annotations

import logging

from django.conf import settings
from django.core.mail import send_mail
from django.template.loader import render_to_string
from django.utils.translation import gettext as _
from django.utils.translation import override

logger = logging.getLogger(__name__)


def _send(*, to: str, subject: str, template: str, context: dict) -> None:
    """
    A single sending point. Errors are logged but never re-raised:
    a failed email must not break an already completed booking.
    """
    try:
        body = render_to_string(template, context)
        send_mail(
            subject=subject,
            message=body,
            from_email=settings.DEFAULT_FROM_EMAIL,
            recipient_list=[to],
            fail_silently=False,
        )
    except Exception:
        # exception() logs the traceback. ERROR rather than CRITICAL:
        # a failed email does not break an already completed booking.
        logger.exception("Failed to send %s to %s", template, to)


def send_booking_created_emails(booking_id: int) -> None:
    """
    Emails to both parties when a booking is created. Takes a pk rather than
    an object: the call is deferred until commit, by which time the in-memory
    instance may be stale.
    """
    from .models import Booking

    booking = (
        Booking.objects.select_related("tenant", "listing", "listing__owner")
        .filter(pk=booking_id)
        .first()
    )
    if booking is None:
        return

    context = {
        "booking": booking,
        "listing": booking.listing,
        "url": f"{settings.SITE_URL}/api/bookings/{booking.public_id}/",
    }

    # override pins the recipient's language. Without it the email goes out
    # in the language of the request that triggered it, i.e. the other
    # party's language.
    with override(booking.tenant.language or settings.LANGUAGE_CODE):
        _send(
            to=booking.tenant.email,
            subject=_("Your booking request has been created"),
            template="emails/booking_created_tenant.txt",
            context=context,
        )
    with override(booking.listing.owner.language or settings.LANGUAGE_CODE):
        _send(
            to = booking.listing.owner.email,
            subject = _("New booking request for your property"),
            template = "emails/booking_created_owner.txt",
            context = context,
    )


def send_booking_status_email(booking_id: int, old_status: str) -> None:
    """
    An email to the tenant about the status change of their booking.
    """
    from .models import Booking, BookingStatus

    booking = (
        Booking.objects.select_related("tenant", "listing")
        .filter(pk=booking_id)
        .first()
    )
    if booking is None:
        return

    subjects = {
        BookingStatus.CONFIRMED: _("Your booking has been confirmed"),
        BookingStatus.REJECTED: _("Your booking has been rejected"),
        BookingStatus.CANCELLED: _("Your booking has been cancelled"),
        BookingStatus.COMPLETED: _("Your stay is complete — leave a review"),
    }
    subject = subjects.get(booking.status)
    if subject is None:
        return

    with override(booking.tenant.language or settings.LANGUAGE_CODE):
        _send(
            to=booking.tenant.email,
            subject=subject,
            template="emails/booking_status_changed.txt",
            context={
                "booking": booking,
                "old_status": old_status,
                "url": f"{settings.SITE_URL}/api/bookings/{booking.public_id}/",
            },
        )