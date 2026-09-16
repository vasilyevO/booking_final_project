# apps/listings/translation.py
from modeltranslation.translator import TranslationOptions, register

from .models import Listing, ListingPhoto


@register(Listing)
class ListingTranslationOptions(TranslationOptions):
    """
    RU: Переводим только пользовательский текст. Город не переводим: это
        имя собственное, и по нему построена нормализация и индексы.
    EN: Only user-facing prose is translated. The city is not: it is a proper
        noun, and the normalisation and indexes are built on it.
    """

    fields = ("title", "description")


@register(ListingPhoto)
class ListingPhotoTranslationOptions(TranslationOptions):
    fields = ("caption",)

# RU: simple-history строит HistoricalListing в момент определения класса,
#     до того как modeltranslation добавит title_en/de/ru. Историческая модель
#     остаётся без этих полей, и post_save падает с TypeError на КАЖДОМ
#     сохранении объявления. Регистрация исторических моделей добавляет
#     колонки и туда — история снова совпадает с оригиналом по набору полей.
# EN: simple-history builds HistoricalListing at class definition time, before
#     modeltranslation adds title_en/de/ru. The historical model is left without
#     those fields and post_save fails with a TypeError on EVERY listing save.
#     Registering the historical models adds the columns there too, so history
#     and original share the same field set again.
@register(Listing.history.model)
class HistoricalListingTranslationOptions(TranslationOptions):
    fields = ("title", "description")
