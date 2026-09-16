from __future__ import annotations

from decimal import Decimal

from djmoney import settings as djmoney_settings

from django.db import connections, router
from django.db.transaction import atomic
from djmoney.contrib.exchange.backends.base import BaseExchangeBackend
from djmoney.contrib.exchange.models import ExchangeBackend, Rate


class StaticExchangeBackend(BaseExchangeBackend):
    """
    RU: Фиксированные курсы относительно EUR. Детерминирован, не требует сети
        и ключей API — это для учебного проекта и тестов.
        Боевой вариант: заменить EXCHANGE_BACKEND на FixerBackend
        или OpenExchangeRatesBackend, код проекта при этом не меняется.
    EN: Fixed rates against EUR. Deterministic, needs neither network nor API
        keys — this is for project and its tests require.
        For production: point EXCHANGE_BACKEND at FixerBackend or
        OpenExchangeRatesBackend; the project code stays untouched.
    """

    name = "static"

    RATES: dict[str, Decimal] = {
        "EUR": Decimal("1.0"),
        "USD": Decimal("1.09"),
        "GBP": Decimal("0.85"),
        "PLN": Decimal("4.32"),
        "CZK": Decimal("25.10"),
    }

    def get_rates(self, **params) -> dict[str, Decimal]:
        """
        RU: Курсы к базовой валюте. Вызывается командой update_rates.
        EN: Rates against the base currency. Called by the update_rates command.
        """
        return self.RATES

    @atomic
    def update_rates(self, base_currency: str | None = None, **kwargs) -> None:
        """
        RU: То же, что и в BaseExchangeBackend, но без unique_fields.
            Базовая реализация зовёт bulk_create(update_conflicts=True,
            unique_fields=[...]), а MySQL не умеет указывать цель конфликта:
            supports_update_conflicts_with_target=False, и Django поднимает
            NotSupportedError. В MySQL цель и не нужна — ON DUPLICATE KEY
            UPDATE сам берёт нарушенный уникальный ключ, а он у Rate ровно
            один: unique_together ("currency", "backend").
            На бэкендах с поддержкой цели (PostgreSQL, SQLite) остаётся
            родительская реализация.
        EN: The same as BaseExchangeBackend, minus unique_fields. The parent
            calls bulk_create(update_conflicts=True, unique_fields=[...]), but
            MySQL cannot name a conflict target:
            supports_update_conflicts_with_target=False, so Django raises
            NotSupportedError. MySQL needs no target — ON DUPLICATE KEY UPDATE
            picks the violated unique key itself, and Rate has exactly one:
            unique_together ("currency", "backend").
            On backends that do support a target (PostgreSQL, SQLite) the
            parent implementation is kept.
        """
        if base_currency is None:
            base_currency = djmoney_settings.BASE_CURRENCY

        connection = connections[router.db_for_write(Rate)]
        if connection.features.supports_update_conflicts_with_target:
            return super().update_rates(base_currency, **kwargs)

        backend, _ = ExchangeBackend.objects.update_or_create(
            name=self.name, defaults={"base_currency": base_currency}
        )
        params = self.get_params()
        params.update(base_currency=base_currency, **kwargs)
        Rate.objects.bulk_create(
            [
                Rate(currency=currency, value=value, backend=backend)
                for currency, value in self.get_rates(**params).items()
            ],
            update_conflicts=True,
            update_fields=["value"],
        )