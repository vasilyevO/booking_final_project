from django.contrib import admin
from simple_history.admin import SimpleHistoryAdmin

from .models import Booking


@admin.register(Booking)
class BookingAdmin(SimpleHistoryAdmin):
    list_display = ("listing_title_snapshot", "tenant", "start_date", "end_date", "status", "total_price")
    list_filter = ("status",)
    date_hierarchy = "start_date"
    readonly_fields = ("public_id", "total_price", "price_per_night_snapshot", "listing_title_snapshot")