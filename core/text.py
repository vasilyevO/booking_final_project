from __future__ import annotations

# RU: немцы пишут город тремя способами: Köln, Koeln, koln. Полагаться на
#     collation нельзя: utf8mb4_unicode_ci не приравнивает ö ни к o, ни к oe,
#     а между локальной базой и продом collation может разойтись.
# EN: Germans spell a city three ways: Köln, Koeln, koln. Collation is not a
#     reliable answer: utf8mb4_unicode_ci equates ö with neither o nor oe, and
#     the collation may differ between the local database and production.
UMLAUT_MAP = str.maketrans(
    {
        "ä": "ae", "ö": "oe", "ü": "ue", "ß": "ss",
        "Ä": "ae", "Ö": "oe", "Ü": "ue",
        "é": "e", "è": "e", "á": "a", "à": "a",
    }
)


def normalize_search_text(value: str) -> str:
    """
    RU: Складывает умляуты, приводит к нижнему регистру и убирает пробелы
        по краям. Результат кладётся в отдельную колонку для поиска —
        отображаемое значение остаётся нетронутым.
    EN: Folds umlauts, lowercases and strips the value. The result goes into a
        dedicated search column; the displayed value is left untouched.
    """
    if not value:
        return ""
    return value.strip().translate(UMLAUT_MAP).lower()