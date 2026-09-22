from modeltranslation.translator import TranslationOptions, register

from .models import Listing, ListingPhoto


@register(Listing)
class ListingTranslationOptions(TranslationOptions):
    """
    Only user-facing prose is translated. The city is not: it is a proper
    noun, and the normalisation and indexes are built on it.
    """

    fields = ("title", "description")


@register(ListingPhoto)
class ListingPhotoTranslationOptions(TranslationOptions):
    fields = ("caption",)

# simple-history builds HistoricalListing at class definition time, before
# modeltranslation adds title_en/de/ru. The historical model is left without
# those fields and post_save would fail with a TypeError on every save.
# Registering the historical model adds the columns there too, so history
# and original share the same field set.
@register(Listing.history.model)
class HistoricalListingTranslationOptions(TranslationOptions):
    fields = ("title", "description")
