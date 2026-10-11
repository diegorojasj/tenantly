"""The Spanish overlays seeded by migration 0012 word exactly what the templates hold."""

from __future__ import annotations

from importlib import import_module
from typing import Any

import pytest
from src.models import Template

pytestmark = pytest.mark.django_db

ES = import_module("src.migrations.0012_seed_spanish").ES

# What a template's words are: field -> sub-shape; `True` marks a word, a list wraps its items' shape.
FIELDS = [{"label": True}]
WORDS: dict[str, Any] = {
    "label": True,
    "description": True,
    "terms": "*",
    "status": "*",
    "presets": [{"label": True, "plural": True, "intro": True}],
    "resourceTypes": [{"label": True, "plural": True, "roleLabel": True, "attributes": FIELDS}],
    "fields": {"*": FIELDS},
    "accountTypes": [{"label": True, "plural": True, "fields": FIELDS}],
    "subjectTypes": [{"label": True, "plural": True, "fields": FIELDS}],
    "documents": [{"label": True}],
    "levels": [{"label": True, "plural": True}],
    "roles": [{"label": True, "summary": True}],
}


def _identity(item: dict[str, Any]) -> str:
    return item.get("key", item.get("id"))


def _words(base: Any, shape: Any, path: str = "") -> set[str]:
    """Every word path of `base` (list items named by key/id), following `shape`."""
    if shape is True or (shape == "*" and not isinstance(base, dict)):
        return {path} if isinstance(base, str) and base else set()
    if shape == "*":
        return {f"{path}.{k}" for k, v in base.items() if isinstance(v, str) and v}
    if isinstance(shape, list):
        return set().union(*(_words(item, shape[0], f"{path}[{_identity(item)}]") for item in base))
    paths: set[str] = set()
    for key, value in base.items():
        sub = shape.get(key, shape.get("*"))
        if sub is not None:
            paths |= _words(value, sub, f"{path}.{key}")
    return paths


def _leaves(overlay: Any, path: str = "") -> set[str]:
    """Every leaf path of `overlay`; asserts each list item names its item and each leaf is a string."""
    if isinstance(overlay, dict):
        return set().union(set(), *(_leaves(v, f"{path}.{k}") for k, v in overlay.items()))
    if isinstance(overlay, list):
        paths: set[str] = set()
        for item in overlay:
            assert isinstance(item, dict), path
            name = _identity(item)
            assert isinstance(name, str), f"{path}: item without key/id"
            paths |= _leaves({k: v for k, v in item.items() if k not in {"key", "id"}}, f"{path}[{name}]")
        return paths
    assert isinstance(overlay, str), f"{path}: {overlay!r} is not a word"
    assert overlay.strip(), f"{path}: empty"
    return {path}


def _legacy(template_id: str) -> dict[str, Any]:
    """A legacy template's wire shape, rebuilt from the frozen data of 0004 -> 0006 -> 0007 -> 0009
    (0010 deletes the ones no business uses, so a fresh database has none)."""
    m4, m6, m7, m9 = (
        import_module(f"src.migrations.{name}")
        for name in (
            "0004_seed_templates",
            "0006_template_presets_resource_types",
            "0007_template_parties_fields_documents",
            "0009_seed_levels_and_roles",
        )
    )
    seed = next(t for t in m4.TEMPLATES if t["id"] == template_id)
    pii = m7.PII.get(template_id, set())
    return {
        "label": seed["label"],
        "description": seed["description"],
        "presets": [{"key": k, **m6.PRESETS[k]} for k in seed["kinds"]],
        "resourceTypes": m6._resource_types(template_id, seed["terms"]),
        "terms": seed["terms"],
        "status": seed["status"],
        "fields": {
            "customer": [
                {**f, "type": "text", **({"pii": True} if f["key"] in pii else {})} for f in seed["customer_fields"]
            ]
        },
        "accountTypes": m7.ACCOUNT_TYPES.get(template_id, []),
        "subjectTypes": m7.SUBJECT_TYPES.get(template_id, []),
        "documents": ([m7.WAIVER] if seed["waiver"] else []) + m7.EXTRA_DOCUMENTS.get(template_id, []),
        "levels": [m9.AREA],
        "roles": m9.ROLES,
    }


def _base(template_id: str) -> dict[str, Any]:
    if template_id == "general":
        return Template.objects.get(id="general").base_dict()
    return _legacy(template_id)


@pytest.mark.parametrize("template_id", ["general", "fitness", "rentals", "field"])
def test_spanish_overlay_words_every_word_and_nothing_else(template_id: str) -> None:
    base_words = _words(_base(template_id), WORDS)
    overlay_words = _leaves(ES[template_id])
    assert not overlay_words - base_words, "orphan or non-word paths"
    assert not base_words - overlay_words, "untranslated words"


def test_seeded_general_template_reads_in_spanish() -> None:
    template = Template.objects.get(id="general")
    assert template.as_dict("es")["terms"]["customer"] == "Cliente"
    assert template.as_dict("en")["terms"]["customer"] == "Customer"
    spanish = template.as_dict("es")
    # Stored values stay as they are; only words change.
    assert spanish["transitions"] == template.base_dict()["transitions"]
    assert [p["units"] for p in spanish["presets"]] == [p["units"] for p in template.presets]
    assert {r["id"]: r["label"] for r in spanish["roles"]}["owner"] == "Propietario"
