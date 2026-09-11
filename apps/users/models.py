from __future__ import annotations

from django.contrib.auth.models import AbstractUser, BaseUserManager
from django.db import models
from django.utils.translation import gettext_lazy as _

from core.models import PublicIdModel, TimeStampedModel


class UserManager(BaseUserManager):
    """
    RU: Менеджер пользователей с логином по email вместо username.
    EN: User manager using email as the login field instead of username.
    """

    use_in_migrations = True

    def _create_user(self, email: str, password: str | None, **extra_fields) -> "User":
        """
        RU: Общая логика создания пользователя с нормализацией email.
        EN: Shared user creation logic with email normalisation.
        """
        if not email:
            raise ValueError("Email is required")
        user = self.model(email=self.normalize_email(email), **extra_fields)
        user.set_password(password)
        user.save(using=self._db)
        return user

    def create_user(self, email: str, password: str | None = None, **extra_fields) -> "User":
        """
        RU: Создаёт обычного пользователя. Права выдаются добавлением в группу,
            а не полем модели.
        EN: Creates a regular user. Permissions come from group membership,
            not from a model field.
        """
        extra_fields.setdefault("is_staff", False)
        extra_fields.setdefault("is_superuser", False)
        return self._create_user(email, password, **extra_fields)

    def create_superuser(self, email: str, password: str | None = None, **extra_fields) -> "User":
        """
        RU: Создаёт суперпользователя для админки.
        EN: Creates a superuser for the admin site.
        """
        extra_fields.setdefault("is_staff", True)
        extra_fields.setdefault("is_superuser", True)
        if extra_fields.get("is_staff") is not True:
            raise ValueError("Superuser must have is_staff=True")
        return self._create_user(email, password, **extra_fields)


class User(AbstractUser, TimeStampedModel, PublicIdModel):
    """
    RU: Пользователь системы. Роли не хранятся в модели — они выражены
        членством в группах Django, чтобы источник истины был один.
    EN: Application user. Roles are not stored on the model — they are
        expressed through Django group membership, keeping one source of truth.
    """

    # RU: username убран — идентификатором служит email.
    # EN: username removed — email is the identifier.
    username = None
    email = models.EmailField(_("email"), unique=True)
    # RU: для строковых полей используем blank="" вместо null.
    # EN: for string fields prefer blank="" over null.
    phone = models.CharField(max_length=32, blank=True)

    USERNAME_FIELD = "email"
    REQUIRED_FIELDS: list[str] = []

    objects = UserManager()

    class Meta:
        verbose_name = "Пользователь"
        verbose_name_plural = "Пользователи"
        ordering = ("-date_joined",)

    def __str__(self) -> str:
        return self.email