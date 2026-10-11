"""Business-wide settings: money (gap 9) and branding with an SSO placeholder (gap 10).

Money settings travel in every tenant token (`money` claim), so billing and operations
pick up a change within a token's lifetime. Branding is shown by the frontend; the
custom domain is recorded and kept unique, but routing it is the deployment's job.
SSO settings are stored only: nothing contacts an identity provider yet, and sign-in
stays email and password.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from decimal import Decimal
from typing import TYPE_CHECKING, Any

from django.core.exceptions import ValidationError
from django.core.validators import URLValidator
from django.db import transaction
from django.utils.translation import gettext as _

from common.errors import ConflictError, InvalidError, NotFoundError
from common.money import CURRENCIES, is_currency

from ..models import Tenant
from . import ledger

if TYPE_CHECKING:
    from common.auth import TenantClaims

_HOST = re.compile(r"^(?=.{4,253}$)(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z]{2,63}$")
_HTTPS = URLValidator(schemes=["https"])
SSO_PROTOCOLS = ("none", "saml", "oidc")
MAX_TAX = Decimal(100)


@dataclass(frozen=True)
class SettingsPatch:
    """`None` leaves a setting as it is."""

    currency: str | None = None
    tax_rate: Decimal | None = None
    tax_label: str | None = None
    prices_include_tax: bool | None = None
    logo_url: str | None = None
    custom_domain: str | None = None
    sso: dict[str, Any] | None = None


def sso_dict(tenant: Tenant) -> dict[str, Any]:
    sso = tenant.sso or {}
    return {
        "protocol": sso.get("protocol", "none"),
        "issuer": sso.get("issuer", ""),
        "metadataUrl": sso.get("metadataUrl", ""),
        "clientId": sso.get("clientId", ""),
        # Placeholders until SSO is built: never enforced, never connected.
        "enforced": False,
        "status": "not_connected",
    }


def _tenant(claims: TenantClaims) -> Tenant:
    tenant = Tenant.objects.filter(id=claims.tenant_id).first()
    if not tenant:
        msg = _("No such business")
        raise NotFoundError(msg)
    return tenant


def read(claims: TenantClaims) -> dict[str, Any]:
    claims.demand("tenant.manage")
    tenant = _tenant(claims)
    return {
        "money": tenant.money(),
        "branding": {"logoUrl": tenant.logo_url, "customDomain": tenant.custom_domain or ""},
        "sso": sso_dict(tenant),
        "currencies": list(CURRENCIES),
    }


def _https(value: str, problem: str) -> str:
    value = value.strip()
    if not value:
        return ""
    try:
        _HTTPS(value)
    except ValidationError as exc:
        raise InvalidError(problem) from exc
    return value


def _money_changes(tenant: Tenant, patch: SettingsPatch) -> list[str]:
    changes: list[str] = []
    if patch.currency is not None and patch.currency.strip().upper() != tenant.currency:
        code = patch.currency.strip().upper()
        if not is_currency(code):
            msg = _("Pick a currency")
            raise InvalidError(msg)
        tenant.currency = code
        changes.append(f"currency {code}")
    if patch.tax_rate is not None and patch.tax_rate != tenant.tax_rate:
        if not Decimal(0) <= patch.tax_rate <= MAX_TAX:
            msg = _("Tax is a percentage between 0 and 100")
            raise InvalidError(msg)
        tenant.tax_rate = patch.tax_rate
        changes.append(f"tax {patch.tax_rate}%")
    if patch.tax_label is not None and patch.tax_label.strip() != tenant.tax_label:
        label = patch.tax_label.strip()
        if not 0 < len(label) <= 20:  # noqa: PLR2004
            msg = _("Name the tax (VAT, GST, Sales tax)")
            raise InvalidError(msg)
        tenant.tax_label = label
        changes.append(f"tax called {label}")
    if patch.prices_include_tax is not None and patch.prices_include_tax != tenant.prices_include_tax:
        tenant.prices_include_tax = patch.prices_include_tax
        changes.append("prices include tax" if patch.prices_include_tax else "tax added on top of prices")
    return changes


def _branding_changes(tenant: Tenant, patch: SettingsPatch) -> list[str]:
    changes: list[str] = []
    if patch.logo_url is not None and patch.logo_url.strip() != tenant.logo_url:
        tenant.logo_url = _https(patch.logo_url, _("The logo must be an https:// address"))
        changes.append("logo" if tenant.logo_url else "logo removed")
    if patch.custom_domain is not None:
        domain = patch.custom_domain.strip().lower().rstrip(".") or None
        if domain != tenant.custom_domain:
            if domain and not _HOST.match(domain):
                msg = _("“%(domain)s” is not a domain name (use one like book.example.com)") % {"domain": domain}
                raise InvalidError(msg)
            if domain and Tenant.objects.filter(custom_domain=domain).exclude(id=tenant.id).exists():
                msg = _("That domain is already used by another business")
                raise ConflictError(msg)
            tenant.custom_domain = domain
            changes.append(f"domain {domain}" if domain else "domain removed")
    return changes


def _sso_changes(tenant: Tenant, sso: dict[str, Any] | None) -> list[str]:
    if sso is None:
        return []
    protocol = sso.get("protocol", "none")
    if protocol not in SSO_PROTOCOLS:
        msg = _("Pick SAML, OpenID Connect or none")
        raise InvalidError(msg)
    stored = {
        "protocol": protocol,
        "issuer": _https(str(sso.get("issuer") or ""), _("The issuer must be an https:// address")),
        "metadataUrl": _https(str(sso.get("metadataUrl") or ""), _("The metadata URL must be an https:// address")),
        "clientId": str(sso.get("clientId") or "").strip()[:200],
    }
    if protocol == "saml" and not stored["metadataUrl"]:
        msg = _("SAML needs the identity provider's metadata URL")
        raise InvalidError(msg)
    if protocol == "oidc" and not (stored["issuer"] and stored["clientId"]):
        msg = _("OpenID Connect needs the issuer and a client ID")
        raise InvalidError(msg)
    if stored == {k: (tenant.sso or {}).get(k, "none" if k == "protocol" else "") for k in stored}:
        return []
    tenant.sso = stored
    return [f"single sign-on: {protocol} (saved, not active)"]


@transaction.atomic
def update(claims: TenantClaims, patch: SettingsPatch) -> dict[str, Any]:
    claims.demand("tenant.manage")
    tenant = Tenant.objects.select_for_update().get(id=claims.tenant_id)
    money = _money_changes(tenant, patch)
    branding = _branding_changes(tenant, patch)
    sso = _sso_changes(tenant, patch.sso)
    if money or branding or sso:
        tenant.save()
    for category, changes in (("billing", money), ("config", branding), ("security", sso)):
        if changes:
            ledger.append(
                claims.tenant_id,
                {
                    "actor_id": claims.user_id,
                    "actor_name": claims.user_name,
                    "action": "tenant.updated",
                    "category": category,
                    "target": f"{tenant.name}: {', '.join(changes)}",
                    "scope_id": claims.home_scope_id,
                    "scope_name": claims.name_of(claims.home_scope_id),
                },
            )
    return read(claims)
