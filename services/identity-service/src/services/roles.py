"""A business's own roles (docs/PLATFORM.md gap 8).

Each business starts with its template's default roles and may edit them, add its
own and remove unused ones. One rule keeps this from becoming an escalation path:
nobody creates, edits or removes a role that can do something their own role can't,
and nobody edits the role they hold. `owner` is fixed and holds every permission.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from django.conf import settings
from django.db import transaction
from django.utils import translation
from django.utils.text import slugify
from django.utils.translation import gettext as _
from django.utils.translation import ngettext

from common.errors import ConflictError, ForbiddenError, InvalidError, NotFoundError
from common.i18n import localize

from ..models import Membership, Role
from ..types.roles import OWNER, OWNER_ONLY, PERMISSION_LABELS, ROLES
from . import ledger

if TYPE_CHECKING:
    from common.auth import TenantClaims

    from ..models import Template, Tenant

MIN_LABEL = 2
KEY_LENGTH = 20


def role_dict(r: Role, members: int | None = None) -> dict[str, Any]:
    words = localize({"label": r.label, "summary": r.summary}, r.translations)
    data: dict[str, Any] = {
        "id": r.key,
        "label": words["label"],
        "summary": words["summary"],
        # The owner holds every permission, including ones added after the business was created.
        "permissions": list(PERMISSION_LABELS)
        if r.key == OWNER
        # Owner-only permissions a role row still lists (from before they were) grant nothing.
        else [p for p in r.permissions if p in PERMISSION_LABELS and p not in OWNER_ONLY],
        "builtin": r.builtin,
    }
    if members is not None:
        data["members"] = members
    return data


def _worded(r: dict[str, Any], lang: str) -> dict[str, str]:
    """A default role's label and summary in `lang` (the platform's are translated in code)."""
    with translation.override(lang):
        return {"label": str(r["label"]), "summary": str(r.get("summary", ""))}


def seed(tenant: Tenant, template: Template) -> None:
    """Copy the template's default roles into a new business; `owner` is always among them.

    Each keeps its wording in every language, so a business reads its starting roles in
    whichever language it uses until it renames them.
    """
    langs = [code for code, _ in settings.LANGUAGES]
    worded = {lang: {r["id"]: r for r in template.as_dict(lang)["roles"]} for lang in langs}
    defaults = list(template.roles) or ROLES
    if not any(r["id"] == OWNER for r in defaults):
        defaults = [next(r for r in ROLES if r["id"] == OWNER), *defaults]
    for r in defaults:
        words = {lang: _worded(worded[lang].get(r["id"], r), lang) for lang in langs}
        base = words.pop(settings.LANGUAGE_CODE)
        Role.objects.create(
            tenant=tenant,
            key=r["id"],
            label=base["label"],
            summary=base["summary"],
            permissions=list(r["permissions"]),
            builtin=True,
            translations=words,
        )


def _reworded(r: Role, field: str) -> None:
    """The business wrote this field itself: its words now stand in every language."""
    for words in r.translations.values():
        words.pop(field, None)


def of(tenant_id: str, key: str) -> dict[str, Any] | None:
    r = Role.objects.filter(tenant_id=tenant_id, key=key).first()
    return role_dict(r) if r else None


def require(tenant_id: str, key: str) -> dict[str, Any]:
    found = of(tenant_id, key) if key else None
    if not found:
        msg = _("Pick a role")
        raise InvalidError(msg)
    return found


def listing(claims: TenantClaims) -> dict[str, Any]:
    claims.demand_any(("members.invite", "roles.assign"))
    counts: dict[str, int] = {}
    for key in Membership.objects.filter(tenant_id=claims.tenant_id).values_list("role", flat=True):
        counts[key] = counts.get(key, 0) + 1
    rows = Role.objects.filter(tenant_id=claims.tenant_id)
    return {
        "roles": [role_dict(r, counts.get(r.key, 0)) for r in rows],
        "permissions": [(key, str(label)) for key, label in PERMISSION_LABELS.items()],
        "ownerOnly": sorted(OWNER_ONLY),
        "canEdit": claims.can("roles.assign"),
    }


# ------------------------------------------------------------- writing --


def check_grant(claims: TenantClaims, permissions: list[str], what: str) -> None:
    """Nobody hands out more than they hold, or a role becomes a privilege escalation."""
    extra = set(permissions) - set(claims.permissions)
    if extra:
        msg = _("You can't grant %(role)s: it can do things your role can't") % {"role": what}
        raise ForbiddenError(msg)


def _clean_permissions(permissions: list[str]) -> list[str]:
    unknown = [p for p in permissions if p not in PERMISSION_LABELS]
    if unknown:
        msg = _("Unknown permission: %(permission)s") % {"permission": unknown[0]}
        raise InvalidError(msg)
    if OWNER_ONLY & set(permissions):
        msg = _("Only the owner manages the Tenantly plan: no other role can")
        raise ForbiddenError(msg)
    # Stored in the catalogue's order, so the matrix and diffs read the same everywhere.
    return [p for p in PERMISSION_LABELS if p in set(permissions)]


def _clean_label(claims: TenantClaims, label: str, exclude: str | None = None) -> str:
    label = label.strip()
    if len(label) < MIN_LABEL or len(label) > 60:  # noqa: PLR2004
        msg = _("Name the role (2 to 60 characters)")
        raise InvalidError(msg)
    clash = Role.objects.filter(tenant_id=claims.tenant_id, label__iexact=label)
    if exclude:
        clash = clash.exclude(key=exclude)
    if clash.exists():
        msg = _("There's already a role called %(label)s") % {"label": label}
        raise ConflictError(msg)
    return label


def _unique_key(tenant_id: str, label: str) -> str:
    base = slugify(label).replace("-", "_")[:KEY_LENGTH].strip("_") or "role"
    key, n = base, 2
    while Role.objects.filter(tenant_id=tenant_id, key=key).exists():
        suffix = f"_{n}"
        key = f"{base[: KEY_LENGTH - len(suffix)]}{suffix}"
        n += 1
    return key


def _editable(claims: TenantClaims, key: str) -> Role:
    claims.demand("roles.assign")
    r = Role.objects.select_for_update().filter(tenant_id=claims.tenant_id, key=key).first()
    if not r:
        msg = _("No such role")
        raise NotFoundError(msg)
    if r.key == OWNER:
        msg = _("The owner role can't be changed")
        raise ForbiddenError(msg)
    if r.key == claims.role:
        msg = _("You can't change the role you hold")
        raise ForbiddenError(msg)
    check_grant(claims, r.permissions, r.label)
    return r


def _audit(claims: TenantClaims, action: str, target: str) -> None:
    ledger.append(
        claims.tenant_id,
        {
            "actor_id": claims.user_id,
            "actor_name": claims.user_name,
            "action": action,
            "category": "access",
            "target": target,
            "scope_id": claims.home_scope_id,
            "scope_name": claims.name_of(claims.home_scope_id),
        },
    )


@transaction.atomic
def create(claims: TenantClaims, *, label: str, summary: str, permissions: list[str]) -> dict[str, Any]:
    claims.demand("roles.assign")
    label = _clean_label(claims, label)
    perms = _clean_permissions(permissions)
    check_grant(claims, perms, label)
    r = Role.objects.create(
        tenant_id=claims.tenant_id,
        key=_unique_key(claims.tenant_id, label),
        label=label,
        summary=summary.strip()[:200],
        permissions=perms,
    )
    _audit(claims, "role.created", f"{label}: {', '.join(perms) or 'no permissions'}")
    return role_dict(r, 0)


@transaction.atomic
def update(
    claims: TenantClaims, key: str, *, label: str | None, summary: str | None, permissions: list[str] | None
) -> dict[str, Any]:
    r = _editable(claims, key)
    # Compare with what the editor was shown: the role in their language.
    shown = role_dict(r)
    changes: list[str] = []
    if label is not None and label.strip() != shown["label"]:
        r.label = _clean_label(claims, label, exclude=r.key)
        _reworded(r, "label")
        changes.append(f"renamed to {r.label}")
    if summary is not None and summary.strip() != shown["summary"]:
        r.summary = summary.strip()[:200]
        _reworded(r, "summary")
        changes.append("summary")
    if permissions is not None:
        perms = _clean_permissions(permissions)
        check_grant(claims, perms, r.label)
        added = [p for p in perms if p not in r.permissions]
        removed = [p for p in r.permissions if p not in perms]
        changes += [f"+{p}" for p in added] + [f"-{p}" for p in removed]
        r.permissions = perms
    if changes:
        r.save()
        _audit(claims, "role.updated", f"{r.label}: {', '.join(changes)}")
    return role_dict(r, Membership.objects.filter(tenant_id=claims.tenant_id, role=r.key).count())


@transaction.atomic
def delete(claims: TenantClaims, key: str) -> None:
    r = _editable(claims, key)
    holders = Membership.objects.filter(tenant_id=claims.tenant_id, role=r.key).count()
    if holders:
        msg = ngettext(
            "%(n)s person holds %(role)s: give them another role first",
            "%(n)s people hold %(role)s: give them another role first",
            holders,
        ) % {"n": holders, "role": r.label}
        raise ConflictError(msg)
    r.delete()
    _audit(claims, "role.deleted", r.label)
