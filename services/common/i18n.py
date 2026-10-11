"""Languages the services answer in, and translated overlays for stored data.

Code strings (errors, labels) use Django's gettext: each request runs in the
language its `Accept-Language` names (LocaleMiddleware, see `settings.build`),
and service-to-service calls forward it (`internal.call`). Catalogs live in
`common/locale` and each service's `src/locale`; `scripts/messages.sh`
refreshes and compiles them.

Stored data a business reads (template vocabulary, statuses, presets, field
labels…) can't go through gettext: it is data, edited without a deploy. It
carries a `translations` map instead, `{lang: overlay}`, where an overlay has
the data's own shape but only the words. `localize` lays the overlay for the
active language over the base:

- dicts merge key by key, recursively;
- lists of objects merge item by item on their `key` (or `id`), so a
  translation names the item it words and never depends on order;
- anything else (strings, numbers, lists of plain values such as choice
  options, which are stored values) is replaced.

Nothing has to know which fields are words, so a field added to the data
later is translatable the day it exists.
"""

from __future__ import annotations

from typing import Any

from django.utils.translation import get_language

LANGUAGES = [("en", "English"), ("es", "Español")]
DEFAULT = "en"


def language() -> str:
    """The active request's language, reduced to one we serve (`es-MX` -> `es`)."""
    lang = (get_language() or DEFAULT).split("-")[0].lower()
    return lang if lang in dict(LANGUAGES) else DEFAULT


def _identity(item: Any) -> Any:
    return item.get("key", item.get("id")) if isinstance(item, dict) else None


def overlay(base: Any, words: Any) -> Any:
    """`base` with `words` laid over it (see the module docstring for the rules)."""
    if isinstance(base, dict) and isinstance(words, dict):
        return {k: overlay(base[k], words[k]) if k in words else base[k] for k in base} | {
            k: v for k, v in words.items() if k not in base
        }
    if isinstance(base, list) and isinstance(words, list) and all(_identity(i) is not None for i in base):
        by_id = {_identity(w): w for w in words if _identity(w) is not None}
        return [overlay(item, by_id[_identity(item)]) if _identity(item) in by_id else item for item in base]
    return words


def localize(base: Any, translations: dict[str, Any] | None, lang: str | None = None) -> Any:
    """`base` in `lang` (the request's language by default); the base itself when there's no overlay."""
    words = (translations or {}).get(lang or language())
    return overlay(base, words) if words else base
