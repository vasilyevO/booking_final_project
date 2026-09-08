# apps/users/signals.py
from __future__ import annotations

from django.contrib.auth.models import Group
from django.db.models.signals import post_save
from django.dispatch import receiver

from .models import User

@receiver(post_save, sender=User)
def sync_user_group(sender: type[User], instance: User, created: bool, **kwargs) -> None:
    """
    RU: Синхронизирует поле role с одноимённой группой, где хранятся permissions.
    EN: Keeps the role field in sync with the group of the same name holding permissions.
    """
    group, _created = Group.objects.get_or_create(name=instance.role)
    instance.groups.set([group])