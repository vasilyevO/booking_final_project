from django.contrib import admin
from simple_history.admin import SimpleHistoryAdmin

from .models import Listing, ListingPhoto
from modeltranslation.admin import TranslationAdmin



class ListingPhotoInline(admin.TabularInline):
    model = ListingPhoto
    extra = 1
    fields = ("image", "caption", "position")


@admin.register(Listing)
class ListingAdmin(TranslationAdmin, SimpleHistoryAdmin):
    """
    MRO order matters. TranslationAdmin comes first: it overrides form
    rendering and adds the language tabs. SimpleHistoryAdmin only touches
    change_view and the URLs. Swap them and the tabs disappear.
    """

    list_display = ("title", "city", "price_per_night", "rooms", "is_active", "deleted_at")
    list_filter = ("property_type", "is_active", "city")
    search_fields = ("title", "city", "address")
    readonly_fields = (
        "public_id", "city_normalized", "price_base", "created_at", "updated_at",
    )
    inlines = [ListingPhotoInline]

    def get_queryset(self, request):
        return Listing.all_objects.all()