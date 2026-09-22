from __future__ import annotations

from django.conf import settings
from django.db import models
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

from core.models import TimeStampedModel


class SearchQuery(TimeStampedModel):
    """
    A recorded search query used to surface popular keywords.
    """

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="search_queries",
    )
    # store normalised (lower + strip), otherwise "Köln" and "köln" diverge.
    keyword = models.CharField(max_length=200, db_index=True)
    results_count = models.PositiveIntegerField(default=0)

    class Meta:
        verbose_name = _("Search query")
        verbose_name_plural = _("Search history")
        ordering = ("-created_at",)
        indexes = [
            models.Index(fields=("keyword", "-created_at"), name="search_keyword_created_idx")
        ]

    def __str__(self) -> str:
        return self.keyword

class ListingStats(models.Model):
    """
    Aggregated listing counters. A separate table because views are a
    different business process: written orders of magnitude more often,
    need no change history, and must not block booking creation, which
    holds the listings_listing row under select_for_update.
    """

    listing = models.OneToOneField(
        "listings.Listing",
        # PROTECT — analytics outlives the operational data
        on_delete=models.PROTECT,
        related_name="stats",
        primary_key=True,
    )
    views_count = models.PositiveIntegerField(
        default=0,
        verbose_name=_("Views"),
        help_text=_("De-duplicated views, one per user per day"),
    )
    bookings_count = models.PositiveIntegerField(default=0)
    last_viewed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        verbose_name = _("Listing statistics")
        verbose_name_plural = _("Listing statistics")
        indexes = [
            # supports the "most popular first" ordering
            models.Index(fields=("-views_count",), name="stats_views_desc_idx"),
        ]

    def __str__(self) -> str:
        return f"stats of listing {self.listing_id}"


class ListingView(TimeStampedModel):
    """
    Append-only view log, de-duplicated per day.
    """

    listing = models.ForeignKey(
        "listings.Listing",
        # PROTECT: analytics must not vanish with the listing
        on_delete=models.PROTECT,
        related_name="view_records",
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
        verbose_name = _("Listing view")
        verbose_name_plural = _("View history")
        ordering = ("-created_at",)
        constraints = [
            # in MySQL NULL != NULL, so anonymous visitors are de-duplicated
            # by session_key rather than by user.
            models.UniqueConstraint(
                fields=("listing", "user", "session_key", "viewed_on"),
                name="uniq_listing_view_per_day",
            ),
        ]

    def __str__(self) -> str:
        return f"view {self.listing_id} @ {self.viewed_on}"