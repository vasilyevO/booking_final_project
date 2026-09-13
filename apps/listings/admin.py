from django.contrib import admin
from simple_history.admin import SimpleHistoryAdmin

from .models import Listing, ListingPhoto


class ListingPhotoInline(admin.TabularInline):
    model = ListingPhoto
    extra = 1
    fields = ("image", "caption", "position")


@admin.register(Listing)
class ListingAdmin(SimpleHistoryAdmin):
    """
    RU: SimpleHistoryAdmin добавляет кнопку History с разницей изменений —
        ради неё и ставили django-simple-history.
    EN: SimpleHistoryAdmin adds the History button with a diff of changes —
        the very reason django-simple-history was installed.
    """

    list_display = ("title", "city", "price_per_night", "rooms", "is_active", "deleted_at")
    list_filter = ("property_type", "is_active", "city")
    search_fields = ("title", "city", "address")
    readonly_fields = ("public_id", "city_normalized", "created_at", "updated_at")
    inlines = [ListingPhotoInline]

    def get_queryset(self, request):
        """
        RU: В админке показываем и мягко удалённые — иначе их не восстановить.
        EN: The admin shows soft-deleted rows too, otherwise they cannot be restored.
        """
        return Listing.all_objects.all()