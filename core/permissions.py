from __future__ import annotations

from rest_framework import permissions


class ReadOnlyOrModelPermission(permissions.DjangoModelPermissions):
    """
    RU: Чтение открыто всем, включая анонимов; запись требует права модели,
        то есть членства в соответствующей группе.
    EN: Reading is open to everyone including anonymous users; writing requires
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
    RU: Групповое право отвечает «может ли он вообще редактировать объявления»,
        а этот класс — «его ли это объявление». Одних групп недостаточно.
    EN: The group permission answers "may they edit listings at all", this class
        answers "is this listing theirs". Groups alone are not enough.
    """

    owner_field = "owner"
    message = "Изменять можно только собственные объекты."

    def has_object_permission(self, request, view, obj) -> bool:
        if request.method in permissions.SAFE_METHODS:
            return True
        if request.user.is_staff:
            return True
        return getattr(obj, f"{self.owner_field}_id", None) == request.user.pk


class IsBookingParticipant(permissions.BasePermission):
    """
    RU: Бронь видна только её участникам: арендатору и владельцу жилья.
        Админ видит все.
    EN: A booking is visible only to its participants: the tenant and the
        property owner. Staff see everything.
    """

    message = "Бронирование доступно только его участникам."

    def has_object_permission(self, request, view, obj) -> bool:
        user = request.user
        if user.is_staff:
            return True
        return obj.tenant_id == user.pk or obj.listing.owner_id == user.pk


class IsListingOwner(permissions.BasePermission):
    """
    RU: Подтверждать и отклонять бронь может только владелец жилья.
    EN: Only the property owner may confirm or reject a booking.
    """

    message = "Только владелец жилья может подтвердить или отклонить бронь."

    def has_object_permission(self, request, view, obj) -> bool:
        return request.user.is_staff or obj.listing.owner_id == request.user.pk


class IsReviewAuthor(permissions.BasePermission):
    """
    RU: Править отзыв может только автор и только в течение окна редактирования.
        Удалять не может никто, кроме админа — иначе владелец с плохим
        рейтингом попросит автора стереть отзыв.
    EN: Only the author may edit a review, and only within the edit window.
        Nobody but staff may delete — otherwise a badly rated owner would ask
        the author to remove it.
    """

    message = "Отзыв можно править только автору и только в течение 14 дней."

    def has_object_permission(self, request, view, obj) -> bool:
        if request.method in permissions.SAFE_METHODS:
            return True
        if request.user.is_staff:
            return True
        if request.method == "DELETE":
            return False
        return obj.author_id == request.user.pk and obj.is_editable