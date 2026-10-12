"""Request bodies. Responses are plain dicts already shaped for the frontend's types."""

from __future__ import annotations

from decimal import Decimal
from typing import Literal

from pydantic import Field

from common.schemas import CamelSchema


class LoginIn(CamelSchema):
    email: str
    password: str
    invite: str | None = None


class InviteCodeIn(CamelSchema):
    invite: str


class TenantIn(CamelSchema):
    """A business a Tenantly admin opens for an owner."""

    name: str
    # Every business starts from the generic template; others are for the platform operator.
    template_id: str = "general"
    industry: str = ""
    location_name: str
    currency: str = "USD"


class TokenIn(CamelSchema):
    scope: str | None = None


class NodeIn(CamelSchema):
    parent_id: str
    # "region" is any group (area, franchisee…); `level` names which, else the next level down.
    kind: Literal["region", "location"]
    name: str
    level: str | None = None


class NodePatch(CamelSchema):
    name: str | None = None
    status: str | None = None
    tz: str | None = None
    # Opening hours in minutes from local midnight; `resetHours` goes back to the template's.
    open: int | None = Field(default=None, ge=0, le=24 * 60)
    close: int | None = Field(default=None, ge=0, le=24 * 60)
    reset_hours: bool = False
    # Locations: street address and map pin; `clearPin` takes it off the map.
    address: str | None = Field(default=None, max_length=200)
    lat: float | None = Field(default=None, ge=-90, le=90)
    lng: float | None = Field(default=None, ge=-180, le=180)
    clear_pin: bool = False


class InviteIn(CamelSchema):
    """An invite for an existing account, or (owners only, with `name` and `password`) a new team account."""

    email: str
    role: str
    scope_id: str
    name: str = Field(default="", max_length=120)
    password: str = Field(default="", max_length=200)


class RoleIn(CamelSchema):
    role: str


class RoleDefIn(CamelSchema):
    label: str
    summary: str = ""
    permissions: list[str] = Field(default_factory=list)


class RoleDefPatch(CamelSchema):
    label: str | None = None
    summary: str | None = None
    permissions: list[str] | None = None


class SsoIn(CamelSchema):
    protocol: Literal["none", "saml", "oidc"] = "none"
    issuer: str = ""
    metadata_url: str = ""
    client_id: str = ""


class SettingsIn(CamelSchema):
    currency: str | None = None
    tax_rate: Decimal | None = Field(default=None, ge=0, le=100, max_digits=5, decimal_places=2)
    tax_label: str | None = None
    prices_include_tax: bool | None = None
    logo_url: str | None = Field(default=None, max_length=500)
    custom_domain: str | None = Field(default=None, max_length=253)
    sso: SsoIn | None = None


class AuditIn(CamelSchema):
    tenant_id: str
    actor_id: str
    actor_name: str
    action: str
    category: Literal["access", "config", "billing", "integration", "security"]
    target: str
    scope_id: str | None = None
    scope_name: str = ""


class PlanTermsIn(CamelSchema):
    """What a Custom plan was negotiated at: a monthly price, active customers it includes
    (none: no limit), and what each one past them costs (none: no overage)."""

    price: Decimal = Field(ge=0, max_digits=10, decimal_places=2)
    customer_limit: int | None = Field(default=None, ge=1)
    overage_price: Decimal | None = Field(default=None, ge=0, max_digits=10, decimal_places=2)


class PlanIn(CamelSchema):
    """Set by Tenantly staff (`manage.py set_plan`), never by the business; billing applies it."""

    plan: Literal["Starter", "Growth", "Enterprise", "Custom"]
    terms: PlanTermsIn | None = None
    reason: str = Field(default="", max_length=200)


# ------------------------------------------------------- admin console --


class AdminPlanIn(CamelSchema):
    """A Tenantly admin moves a business to a plan; billing prices and records it."""

    plan: Literal["starter", "growth", "enterprise", "custom"]
    terms: PlanTermsIn | None = None
    reason: str = Field(min_length=1, max_length=200)


class AdminGrantIn(CamelSchema):
    kind: Literal["extra_allowance", "discount_pct", "waive_overage", "extend_grace", "dispute"]
    metric: Literal["active_customers", ""] = ""
    value: Decimal = Field(default=Decimal(0), ge=0, max_digits=10, decimal_places=2)
    days: int = Field(default=31, ge=1, le=366)
    reason: str = Field(min_length=1, max_length=200)


class InvoicePaidIn(CamelSchema):
    reference: str = Field(min_length=1, max_length=120)


class AdminLoginIn(CamelSchema):
    email: str = Field(max_length=254)
    password: str = Field(max_length=200)


class OwnerIn(CamelSchema):
    """A new business owner: their account, their first business and the plan it starts on."""

    name: str = Field(max_length=120)
    email: str = Field(max_length=254)
    password: str = Field(max_length=200)
    business: TenantIn
    plan: Literal["starter", "growth", "enterprise"] = "starter"
    reason: str = Field(min_length=1, max_length=200)


class BusinessIn(CamelSchema):
    """Another business for an existing owner, on its own plan."""

    business: TenantIn
    plan: Literal["starter", "growth", "enterprise"] = "starter"
    reason: str = Field(min_length=1, max_length=200)


class OwnerStatusIn(CamelSchema):
    """Restricted: signs in and reads, changes nothing. Suspended: no sign-in at all."""

    status: Literal["active", "restricted", "suspended"]
    reason: str = Field(min_length=1, max_length=200)


class RepriceIn(CamelSchema):
    """A plan's new price list. Billing publishes it as a new version; nothing issued changes."""

    price: Decimal = Field(ge=0, max_digits=10, decimal_places=2)
    included: int | None = Field(default=None, ge=1)
    overage_price: Decimal | None = Field(default=None, ge=0, max_digits=10, decimal_places=2)
    cap: Decimal | None = Field(default=None, ge=0, max_digits=10, decimal_places=2)
    reason: str = Field(min_length=1, max_length=200)


class PolicyIn(CamelSchema):
    """The whole billing policy as it should read from now on; billing validates and versions it."""

    limit_after_days: int
    restrict_after_days: int
    cancel_after_days: int
    payment_terms_days: int
    small_balance: Decimal = Field(max_digits=10, decimal_places=2)
    extension_days: int
    extension_every_days: int
    retention_days: int
    usage_grace_hours: int
    spend_cap_multiple: Decimal = Field(max_digits=5, decimal_places=2)
    alert_thresholds: list[int] = Field(max_length=4)
    reason: str = Field(min_length=1, max_length=200)
