from __future__ import annotations

from django.contrib.auth.models import AbstractUser, BaseUserManager
from django.db import models
from django.utils.translation import gettext_lazy as _

from core.models import TimeStampedModel


class UserRole(models.TextChoices):
    """
    RU: Роли пользователя: арендатор и арендодатель.
    EN: User roles: tenant and landlord.
    """

    TENANT = "tenant", _("Арендатор")
    LANDLORD = "landlord", _("Арендодатель")


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
        RU: Создаёт обычного пользователя.
        EN: Create a regular user.
        """
        extra_fields.setdefault("is_staff", False)
        extra_fields.setdefault("is_superuser", False)
        return self._create_user(email, password, **extra_fields)

    def create_superuser(self, email: str, password: str | None = None, **extra_fields) -> "User":
        """
        RU: Создаёт суперпользователя для админки.
        EN: Create a superuser for the admin site.
        """
        extra_fields.setdefault("is_staff", True)
        extra_fields.setdefault("is_superuser", True)
        extra_fields.setdefault("role", UserRole.LANDLORD)
        if extra_fields.get("is_staff") is not True:
            raise ValueError("Superuser must have is_staff=True")
        return self._create_user(email, password, **extra_fields)


class User(AbstractUser, TimeStampedModel):
    """
    RU: Пользователь системы. Заменяет стандартную модель Django,
        поэтому объявлена до первой миграции.
    EN: Application user. Replaces Django's default model, therefore
        declared before the first migration.
    """

    # RU: username убран — идентификатором служит email.
    # EN: username removed — email is the identifier.
    username = None
    email = models.EmailField(_("email"), unique=True)
    role = models.CharField(
        max_length=16,
        choices=UserRole.choices,
        default=UserRole.TENANT,
        db_index=True,
    )
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

    @property
    def is_landlord(self) -> bool:
        """
        RU: True, если пользователь может публиковать объявления.
        EN: True if the user is allowed to publish listings.
        """
        return self.role == UserRole.LANDLORD

    @property
    def is_tenant(self) -> bool:
        """
        RU: True, если пользователь выступает арендатором.
        EN: True if the user acts as a tenant.
        """
        return self.role == UserRole.TENANT