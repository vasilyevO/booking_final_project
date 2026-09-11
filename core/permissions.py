from __future__ import annotations

from rest_framework import permissions


class HasModelPermission(permissions.DjangoModelPermissions):
    """
    RU: Как DjangoModelPermissions, но требует право и на чтение.
        Базовый класс оставляет GET открытым, нам это не подходит.
    EN: Like DjangoModelPermissions, but also requires a read permission.
        The base class leaves GET open, which is not what we want.
    """

    perms_map = {
        "GET": ["%(app_label)s.view_%(model_name)s"],
        "OPTIONS": [],
        "HEAD": [],
        "POST": ["%(app_label)s.add_%(model_name)s"],
        "PUT": ["%(app_label)s.change_%(model_name)s"],
        "PATCH": ["%(app_label)s.change_%(model_name)s"],
        "DELETE": ["%(app_label)s.delete_%(model_name)s"],
    }


class IsOwnerOrReadOnly(permissions.BasePermission):
    """
    RU: Изменять объект может только его владелец, читать — любой.
        Проверяем действие, а не роль пользователя.
    EN: Only the owner may modify the object, anyone may read it.
        We check the action, not the user's role.
    """

    owner_field = "owner"

    def has_object_permission(self, request, view, obj) -> bool:
        if request.method in permissions.SAFE_METHODS:
            return True
        return getattr(obj, f"{self.owner_field}_id", None) == request.user.pk