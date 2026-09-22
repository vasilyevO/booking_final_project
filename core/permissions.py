from __future__ import annotations

from rest_framework import permissions
from django.utils.translation import gettext_lazy as _


class ReadOnlyOrModelPermission(permissions.DjangoModelPermissions):
    """
    Reading is open to everyone including anonymous users; writing requires
    the model permission, i.e. membership in the matching group.
    """

    perms_map = {
        "GET": [], "OPTIONS": [], "HEAD": [],
        "POST": ["%(app_label)s.add_%(model_name)s"],
        "PUT": ["%(app_label)s.change_%(model_name)s"],
        "PATCH": ["%(app_label)s.change_%(model_name)s"],
        "DELETE": ["%(app_label)s.delete_%(model_name)s"],
    }

    def has_permission(self, request, view) -> bool:
        if request.method in permissions.SAFE_METHODS:
            return True
        return super().has_permission(request, view)


class IsOwnerOrReadOnly(permissions.BasePermission):
    """
    The group permission answers "may they edit listings at all", this class
    answers "is this listing theirs". Groups alone are not enough.
    """

    owner_field = "owner"
    message = _("You may only modify your own objects.")

    def has_object_permission(self, request, view, obj) -> bool:
        if request.method in permissions.SAFE_METHODS:
            return True
        if request.user.is_staff:
            return True
        return getattr(obj, f"{self.owner_field}_id", None) == request.user.pk


class IsBookingParticipant(permissions.BasePermission):
    """
    A booking is visible only to its participants: the tenant and the
    property owner. Staff see everything.
    """

    message = _("A booking is only available to its participants.")

    def has_object_permission(self, request, view, obj) -> bool:
        user = request.user
        if user.is_staff:
            return True
        return obj.tenant_id == user.pk or obj.listing.owner_id == user.pk


class IsListingOwner(permissions.BasePermission):
    """
    Only the property owner may confirm or reject a booking.
    """

    message = _("Only the property owner may confirm or reject a booking.")

    def has_object_permission(self, request, view, obj) -> bool:
        return request.user.is_staff or obj.listing.owner_id == request.user.pk


class IsReviewAuthor(permissions.BasePermission):
    """
    Only the author may edit a review, and only within the edit window.
    Nobody but staff may delete — otherwise a badly rated owner would ask
    the author to remove it.
    """

    message = _("A review may only be edited by its author, within 14 days.")

    def has_object_permission(self, request, view, obj) -> bool:
        if request.method in permissions.SAFE_METHODS:
            return True
        if request.user.is_staff:
            return True
        if request.method == "DELETE":
            return False
        return obj.author_id == request.user.pk and obj.is_editable

class HasBookingActionPermission(permissions.BasePermission):
    """
    RU: Проверяет групповое право на действие с бронью. Объектные классы
        (IsBookingParticipant, IsListingOwner) отвечают на вопрос «его ли
        это бронь», а этот — «может ли он вообще выполнять такое действие».
        Без него бронировать мог любой вошедший, включая чистого
        арендодателя, а права add/confirm/reject/cancel из init_groups
        нигде не применялись.
    EN: Checks the group permission for a booking action. The object-level
        classes (IsBookingParticipant, IsListingOwner) answer "is this
        booking theirs", this one answers "may they perform the action at
        all". Without it any signed-in user could book, including a pure
        landlord, and the add/confirm/reject/cancel permissions granted by
        init_groups were never enforced.
    """

    ACTION_PERMS = {
        "create": "bookings.add_booking",
        "confirm": "bookings.confirm_booking",
        "reject": "bookings.reject_booking",
        "cancel": "bookings.cancel_booking",
    }
    message = _("You do not have permission to perform this booking action.")

    def has_permission(self, request, view) -> bool:
        codename = self.ACTION_PERMS.get(getattr(view, "action", None))
        # RU: list и retrieve прав группы не требуют — видимость ограничена
        #     queryset'ом и IsBookingParticipant.
        # EN: list and retrieve need no group permission — visibility is
        #     limited by the queryset and IsBookingParticipant.
        if codename is None:
            return True
        user = request.user
        return bool(user and user.is_authenticated and (user.is_staff or user.has_perm(codename)))

