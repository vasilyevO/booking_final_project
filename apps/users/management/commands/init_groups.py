from __future__ import annotations

from django.contrib.auth.models import Group, Permission
from django.core.management.base import BaseCommand
from django.db import transaction

# (app_label, model_name, [codename prefixes])
GROUP_MATRIX: dict[str, list[tuple[str, str, list[str]]]] = {
    "tenants": [
        ("listings", "listing", ["view"]),
        ("bookings", "booking", ["add", "view", "cancel"]),
        ("reviews", "review", ["add", "change", "view"]),
    ],
    "landlords": [
        ("listings", "listing", ["add", "change", "delete", "view"]),
        ("bookings", "booking", ["view", "confirm", "reject", "cancel"]),
        ("reviews", "review", ["view"]),
    ],
}


class Command(BaseCommand):
    """
    Creates role groups and assigns permissions to them.
    Idempotent — safe to run on every deployment.
    """

    help = "Create tenant and landlord groups with their permissions"

    @transaction.atomic
    def handle(self, *args, **options) -> None:
        for group_name, rules in GROUP_MATRIX.items():
            group, created = Group.objects.get_or_create(name=group_name)
            permissions: list[Permission] = []

            for app_label, model_name, actions in rules:
                for action in actions:
                    codename = f"{action}_{model_name}"
                    try:
                        permissions.append(
                            Permission.objects.get(
                                codename=codename,
                                content_type__app_label=app_label,
                            )
                        )
                    except Permission.DoesNotExist:
                        self.stderr.write(f"missing permission: {app_label}.{codename}")

            # set() replaces the whole set, keeping the command idempotent
            group.permissions.set(permissions)
            if options["verbosity"] >= 1:
                status = "created" if created else "updated"
                self.stdout.write(self.style.SUCCESS(f"{group_name}: {status}"))