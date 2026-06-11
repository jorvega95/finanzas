"""Text normalization for uniqueness checks. Implements CAT-01 (unaccent + lower)."""

import unicodedata


def normalize_name(name: str) -> str:
    """Lowercase, strip accents and collapse whitespace.

    Portable equivalent of Postgres `unaccent + lower` so SQLite tests and
    Postgres production behave identically (CAT-01).
    """
    decomposed = unicodedata.normalize("NFKD", name.strip().lower())
    without_accents = "".join(c for c in decomposed if not unicodedata.combining(c))
    return " ".join(without_accents.split())
