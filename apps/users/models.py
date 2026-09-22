from __future__ import annotations

from django.contrib.auth.models import AbstractUser, BaseUserManager
from django.db import models
from django.utils.translation import gettext_lazy as _

from core.models import PublicIdModel, TimeStampedModel
from django.conf import settings


class UserManager(BaseUserManager):
    """
    User manager using email as the login field instead of username.
    """

    use_in_migrations = True

    def _create_user(self, email: str, password: str | None, **extra_fields) -> "User":
        """
        Shared user creation logic with email normalisation.
        """
        if not email:
            raise ValueError("Email is required")
        user = self.model(email=self.normalize_email(email), **extra_fields)
        user.set_password(password)
        user.save(using=self._db)
        return user

    def create_user(self, email: str, password: str | None = None, **extra_fields) -> "User":
        """
        Creates a regular user. Permissions come from group membership,
        not from a model field.
        """
        extra_fields.setdefault("is_staff", False)
        extra_fields.setdefault("is_superuser", False)
        return self._create_user(email, password, **extra_fields)

    def create_superuser(self, email: str, password: str | None = None, **extra_fields) -> "User":
        """
        Creates a superuser for the admin site.
        """
        extra_fields.setdefault("is_staff", True)
        extra_fields.setdefault("is_superuser", True)
        if extra_fields.get("is_staff") is not True:
            raise ValueError("Superuser must have is_staff=True")
        return self._create_user(email, password, **extra_fields)


class User(AbstractUser, TimeStampedModel, PublicIdModel):
    """
    Application user. Roles are not stored on the model — they are
    expressed through Django group membership, keeping one source of truth.
    """

    # no username field — email is the identifier.
    username = None
    email = models.EmailField(_("email"), unique=True)
    # for string fields prefer blank="" over null.
    phone = models.CharField(_("Phone"), max_length=32, blank=True)

    language = models.CharField(
        max_length=5,
        choices=settings.LANGUAGES,
        default=settings.LANGUAGE_CODE,
        verbose_name=_("Language"),
        help_text=_("Language used for emails and notifications"),
    )

    USERNAME_FIELD = "email"
    REQUIRED_FIELDS: list[str] = []

    objects = UserManager()

    class Meta:
        verbose_name = _("User")
        verbose_name_plural = _("Users")
        ordering = ("-date_joined",)

    def __str__(self) -> str:
        return self.email