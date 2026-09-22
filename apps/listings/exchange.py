from __future__ import annotations

from decimal import Decimal

from djmoney import settings as djmoney_settings

from django.db import connections, router
from django.db.transaction import atomic
from djmoney.contrib.exchange.backends.base import BaseExchangeBackend
from djmoney.contrib.exchange.models import ExchangeBackend, Rate


class StaticExchangeBackend(BaseExchangeBackend):
    """
    Fixed rates against EUR. Deterministic and needs neither network access
    nor API keys, which suits local development and tests.
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
        Rates against the base currency. Called by the update_rates command.
        """
        return self.RATES

    @atomic
    def update_rates(self, base_currency: str | None = None, **kwargs) -> None:
        """
        The same as BaseExchangeBackend, minus unique_fields. The parent
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