from __future__ import annotations

from django.conf import settings
from django.db import models
from django.utils import timezone

from core.models import TimeStampedModel


class SearchQuery(TimeStampedModel):
    """
    RU: Запись поискового запроса для вывода популярных ключевых слов.
    EN: A recorded search query used to surface popular keywords.
    """

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="search_queries",
    )
    # RU: хранить нормализованным (lower + strip), иначе «Köln» и «köln» разойдутся.
    # EN: store normalised (lower + strip), otherwise "Köln" and "köln" diverge.
    keyword = models.CharField(max_length=200, db_index=True)
    results_count = models.PositiveIntegerField(default=0)

    class Meta:
        verbose_name = "Поисковый запрос"
        verbose_name_plural = "История поиска"
        ordering = ("-created_at",)
        indexes = [
            models.Index(fields=("keyword", "-created_at"), name="search_keyword_created_idx")
        ]

    def __str__(self) -> str:
        return self.keyword


class ListingView(TimeStampedModel):
    """
    RU: Факт просмотра объявления, дедуплицированный по дню.
        История изменений не нужна: записи только создаются.
    EN: A listing view event, de-duplicated per day.
        No change history needed: rows are only ever created.
    """

    listing = models.ForeignKey(
        "listings.Listing", on_delete=models.CASCADE, related_name="view_records"
    )
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="listing_views",
    )
    session_key = models.CharField(max_length=40, blank=True)
    viewed_on = models.DateField(default=timezone.localdate)

    class Meta:
        verbose_name = "Просмотр объявления"
        verbose_name_plural = "История просмотров"
        ordering = ("-created_at",)
        constraints = [
            # RU: в MySQL NULL != NULL, поэтому анонимы дедуплицируются
            #     по session_key, а не по user.
            # EN: in MySQL NULL != NULL, so anonymous visitors are de-duplicated
            #     by session_key rather than by user.
            models.UniqueConstraint(
                fields=("listing", "user", "session_key", "viewed_on"),
                name="uniq_listing_view_per_day",
            ),
        ]

    def __str__(self) -> str:
        return f"view {self.listing_id} @ {self.viewed_on}"