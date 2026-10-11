"""Request bodies. Responses are plain dicts already shaped for the frontend's types."""

from __future__ import annotations

from decimal import Decimal
from typing import Literal

from pydantic import Field

from common.schemas import CamelSchema


class SignupIn(CamelSchema):
    name: str
    email: str
    password: str
    invite: str | None = None


class LoginIn(CamelSchema):
    email: str
    password: str
    invite: str | None = None


class InviteCodeIn(CamelSchema):
    invite: str


class TenantIn(CamelSchema):
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


class InviteIn(CamelSchema):
    email: str
    role: str
    scope_id: str


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
    """What a Custom plan was negotiated at; a limit left out means none."""

    price: Decimal = Field(ge=0, max_digits=10, decimal_places=2)
    customer_limit: int | None = Field(default=None, ge=1)
    payment_limit: int | None = Field(default=None, ge=1)


class PlanIn(CamelSchema):
    """Set by Tenantly (internal route or `manage.py set_plan`), never by the business."""

    plan: Literal["Starter", "Growth", "Enterprise", "Custom"]
    terms: PlanTermsIn | None = None
