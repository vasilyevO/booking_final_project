from __future__ import annotations

# Germans spell a city three ways: Köln, Koeln, koln. Collation is not a
# reliable answer: utf8mb4_unicode_ci equates ö with neither o nor oe, and
# the collation may differ between the local database and production.
UMLAUT_MAP = str.maketrans(
    {
        "ä": "ae", "ö": "oe", "ü": "ue", "ß": "ss",
        "Ä": "ae", "Ö": "oe", "Ü": "ue",
        "é": "e", "è": "e", "á": "a", "à": "a",
    }
)


def normalize_search_text(value: str) -> str:
    """
    Folds umlauts, lowercases and strips the value. The result goes into a
    dedicated search column; the displayed value is left untouched.
    """
    if not value:
        return ""
    return value.strip().translate(UMLAUT_MAP).lower()


# vowels that are written as ae/oe/ue when the umlaut is spelled out
_UMLAUT_BASES = ("a", "o", "u")
# caps the number of variants at 2 ** 6 = 64 for unusually long input
_MAX_VARIANT_POSITIONS = 6


def spelling_variants(value: str) -> set[str]:
    """
    Search forms the user may have meant. The stored form spells umlauts
    out (Köln -> koeln), but people also type the umlaut without its
    diacritic (koln). Every plain a/o/u may therefore stand for ae/oe/ue,
    and all combinations are returned for an IN lookup, which still uses
    the index on the normalised column.
    """
    base = normalize_search_text(value)
    if not base:
        return set()

    positions = [
        index for index, char in enumerate(base)
        if char in _UMLAUT_BASES and base[index + 1:index + 2] != "e"
    ][:_MAX_VARIANT_POSITIONS]

    variants = {base}
    for index in reversed(positions):
        variants |= {v[:index + 1] + "e" + v[index + 1:] for v in variants}
    return variants
