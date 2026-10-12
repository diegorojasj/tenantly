// Tenant administration RPCs: the shell context, team, locations, policies,
// audit trail and the Tenantly plan. Thin on purpose — each
// call forwards the tenant token to the service that owns the data and that
// service decides; mutations name the query keys they refresh.
import { reload, respond } from '@solidjs/web';
import { GET } from '@solidjs/web/server-functions';

import { enterTenant, forgetTenant } from '../server/access';
import { api } from '../server/api';
import type {
  AuditEvent,
  Billing,
  BillingHistory,
  CountedCustomers,
  PlanInvoice,
  BusinessSettings,
  Member,
  Permission,
  ResolvedSetting,
  Role,
  RoleId,
  SettingValue,
  TenantContext,
} from './types';

export const getTenantContext = GET(async (slug: string, scope: string): Promise<TenantContext> => {
  'use server';
  const { jwt: _jwt, can: _can, ...context } = await enterTenant(slug, scope || undefined);
  return context;
});

// ------------------------------------------------------------------ team --

export const getMembers = GET(async (slug: string, scope: string) => {
  'use server';
  const access = await enterTenant(slug, scope || undefined);
  return api<{
    direct: Array<Member>;
    inherited: Array<Member>;
    canAssign: boolean;
    canInvite: boolean;
    /** Only the owner creates accounts; anyone who invites can invite an existing one. */
    canCreateAccounts: boolean;
    viewerId: string;
    seats: number;
  }>('identity', '/tenant/members', { token: access.jwt, query: { scope: access.scopeId } });
});

export const getRoles = GET(async (slug: string) => {
  'use server';
  const access = await enterTenant(slug);
  // `ownerOnly`: permissions no role but the owner's can hold (the Tenantly plan is the owner's).
  return api<{ roles: Array<Role>; permissions: Array<[Permission, string]>; ownerOnly: Array<Permission>; canEdit: boolean }>(
    'identity',
    '/tenant/roles',
    { token: access.jwt },
  );
});

/** Add a role of the business's own; nobody grants permissions their role lacks (identity checks). */
export async function createRole(input: { org: string; label: string; summary: string; permissions: Array<Permission> }) {
  'use server';
  const { org, ...body } = input;
  const access = await enterTenant(org);
  await api('identity', '/tenant/roles', { token: access.jwt, body });
  return reload({ revalidate: ['roles', 'audit'] });
}

export async function updateRole(input: {
  org: string;
  key: RoleId;
  label?: string;
  summary?: string;
  permissions?: Array<Permission>;
}) {
  'use server';
  const { org, key, ...body } = input;
  const access = await enterTenant(org);
  await api('identity', `/tenant/roles/${encodeURIComponent(key)}`, { method: 'PATCH', token: access.jwt, body });
  // Holders' permissions change with their next token.
  forgetTenant(org);
  return reload({ revalidate: ['roles', 'members', 'audit'] });
}

export async function deleteRole(input: { org: string; key: RoleId }) {
  'use server';
  const access = await enterTenant(input.org);
  await api('identity', `/tenant/roles/${encodeURIComponent(input.key)}`, { method: 'DELETE', token: access.jwt });
  return reload({ revalidate: ['roles', 'audit'] });
}

/**
 * Someone with a Tenantly account gets a one-time invite code, returned once to the inviter,
 * who passes the link on. Anyone else needs an account, which only the owner creates here with
 * their name and first password; they join at once and work under the business's plan.
 */
export async function inviteMember(input: {
  org: string;
  email: string;
  role: RoleId;
  scopeId: string;
  name?: string;
  password?: string;
}) {
  'use server';
  const { org, ...body } = input;
  const access = await enterTenant(org);
  const result = await api<{ invite?: string; account?: string }>('identity', '/tenant/members', {
    token: access.jwt,
    body,
  });
  return respond(result, { revalidate: ['members', 'audit'] });
}

export async function changeRole(input: { org: string; memberId: string; role: RoleId }) {
  'use server';
  const access = await enterTenant(input.org);
  await api('identity', `/tenant/members/${input.memberId}`, {
    method: 'PATCH',
    token: access.jwt,
    body: { role: input.role },
  });
  return reload({ revalidate: ['members', 'audit'] });
}

// ------------------------------------------------------------- locations --

/** A location, or a group (`region`) on one of the template's levels (the next one down when omitted). */
export async function addLocation(input: {
  org: string;
  parentId: string;
  kind: 'region' | 'location';
  name: string;
  level?: string;
}) {
  'use server';
  const access = await enterTenant(input.org);
  await api('identity', '/tenant/nodes', {
    token: access.jwt,
    body: { parentId: input.parentId, kind: input.kind, name: input.name, level: input.level ?? null },
  });
  forgetTenant(input.org);
  return reload({ revalidate: ['tenant', 'audit', 'today', 'calendar'] });
}

export async function updateLocation(input: {
  org: string;
  nodeId: string;
  name?: string;
  status?: 'active' | 'paused';
  /** Locations: IANA time zone and opening hours (minutes from local midnight). */
  tz?: string;
  hours?: [number, number] | null;
  /** Locations: street address and map pin `[lat, lng]`; a null pin takes it off the map. */
  address?: string;
  pin?: [number, number] | null;
}) {
  'use server';
  const access = await enterTenant(input.org);
  await api('identity', `/tenant/nodes/${input.nodeId}`, {
    method: 'PATCH',
    token: access.jwt,
    body: {
      name: input.name ?? null,
      status: input.status ?? null,
      tz: input.tz ?? null,
      open: input.hours?.[0] ?? null,
      close: input.hours?.[1] ?? null,
      resetHours: input.hours === null,
      address: input.address ?? null,
      lat: input.pin?.[0] ?? null,
      lng: input.pin?.[1] ?? null,
      clearPin: input.pin === null,
    },
  });
  forgetTenant(input.org);
  return reload({ revalidate: ['tenant', 'audit'] });
}

// -------------------------------------------------------------- policies --

export const getConfig = GET(async (slug: string, scope: string): Promise<Array<ResolvedSetting>> => {
  'use server';
  const access = await enterTenant(slug, scope || undefined);
  return api('operations', '/policies', { token: access.jwt, query: { scope: access.scopeId } });
});

export async function overrideSetting(input: { org: string; scope: string; key: string; value: SettingValue | null }) {
  'use server';
  const access = await enterTenant(input.org, input.scope);
  await api('operations', '/policies', {
    method: 'PUT',
    token: access.jwt,
    body: { scope: access.scopeId, key: input.key, value: input.value },
  });
  return reload({ revalidate: ['config', 'audit', 'today'] });
}

// ----------------------------------------------------------------- audit --

export const getAudit = GET(async (slug: string, scope: string) => {
  'use server';
  const access = await enterTenant(slug, scope || undefined);
  return api<{ events: Array<AuditEvent>; chain: { length: number; intact: boolean; head: string } }>(
    'identity',
    '/tenant/audit',
    { token: access.jwt, query: { scope: access.scopeId } },
  );
});

// -------------------------------------------------------------- business --

export const getSettings = GET(async (slug: string): Promise<BusinessSettings> => {
  'use server';
  const access = await enterTenant(slug);
  return api('identity', '/tenant/settings', { token: access.jwt });
});

export async function updateSettings(input: {
  org: string;
  currency?: string;
  taxRate?: string;
  taxLabel?: string;
  pricesIncludeTax?: boolean;
  logoUrl?: string;
  customDomain?: string;
  sso?: Pick<BusinessSettings['sso'], 'protocol' | 'issuer' | 'metadataUrl' | 'clientId'>;
}) {
  'use server';
  const { org, ...body } = input;
  const access = await enterTenant(org);
  await api('identity', '/tenant/settings', { method: 'PATCH', token: access.jwt, body });
  // Currency, tax and logo live in the tenant context and token: drop the cached ones.
  forgetTenant(org);
  return reload({ revalidate: ['settings', 'tenant', 'workspaces', 'audit'] });
}

// ------------------------------------------------------------------ plan --

// Billing prices everything; these only carry the token. Changes send the
// revision the page showed (a stale page is refused, not obeyed) and an
// Idempotency-Key naming the change *at that revision*, so a repeat of the same
// change (a double click, a retry) finds the one already made instead of failing
// on the revision it moved. The token is dropped after a change so its plan and
// payment standing are fresh on the next request.

export const getBilling = GET(async (slug: string): Promise<Billing> => {
  'use server';
  const access = await enterTenant(slug);
  return api<Billing>('billing', '/plan', { token: access.jwt });
});

export const getBillingHistory = GET(async (slug: string): Promise<BillingHistory> => {
  'use server';
  const access = await enterTenant(slug);
  return api<BillingHistory>('billing', '/plan/history', { token: access.jwt });
});

export const getCountedCustomers = GET(async (slug: string, period: number, offset: number): Promise<CountedCustomers> => {
  'use server';
  const access = await enterTenant(slug);
  return api<CountedCustomers>('billing', '/plan/customers', {
    token: access.jwt,
    query: { period: period || undefined, offset },
  });
});

export const getPlanInvoice = GET(async (slug: string, invoiceId: string): Promise<PlanInvoice> => {
  'use server';
  const access = await enterTenant(slug);
  return api<PlanInvoice>('billing', `/plan/invoices/${encodeURIComponent(invoiceId)}`, { token: access.jwt });
});

const PLAN_KEYS = ['billing', 'billing-history', 'tenant', 'audit'];

async function planWrite(
  org: string,
  path: string,
  options: { key?: string; method?: string; body?: unknown; query?: Record<string, number> },
) {
  const access = await enterTenant(org);
  await api('billing', path, {
    token: access.jwt,
    method: options.method ?? 'POST',
    body: options.body ?? {},
    query: options.query,
    headers: options.key ? { 'idempotency-key': options.key } : undefined,
  });
  forgetTenant(org);
}

/** Upgrades apply now (prorated); downgrades wait for the renewal. Refused while the plan is ending. */
export async function changePlan(input: { org: string; plan: string; revision: number }) {
  'use server';
  await planWrite(input.org, '/plan/change', {
    key: `change:${input.plan}:${input.revision}`,
    body: { plan: input.plan, revision: input.revision },
  });
  return reload({ revalidate: PLAN_KEYS });
}

/** Keep the current plan: drop the change waiting for the renewal (works on Custom and older price lists too). */
export async function withdrawPlanChange(input: { org: string; revision: number }) {
  'use server';
  await planWrite(input.org, '/plan/withdraw', { key: `withdraw:${input.revision}`, query: { revision: input.revision } });
  return reload({ revalidate: PLAN_KEYS });
}

export async function cancelPlan(input: { org: string; revision: number }) {
  'use server';
  await planWrite(input.org, '/plan/cancel', { key: `cancel:${input.revision}`, query: { revision: input.revision } });
  return reload({ revalidate: PLAN_KEYS });
}

export async function resumePlan(input: { org: string; revision: number }) {
  'use server';
  await planWrite(input.org, '/plan/resume', { key: `resume:${input.revision}`, query: { revision: input.revision } });
  return reload({ revalidate: PLAN_KEYS });
}

export async function updatePlanSettings(input: { org: string; spendCap: string | null; alertThresholds: Array<number> }) {
  'use server';
  await planWrite(input.org, '/plan/settings', {
    method: 'PUT',
    body: { spendCap: input.spendCap, alertThresholds: input.alertThresholds },
  });
  return reload({ revalidate: PLAN_KEYS });
}

/** Seven more days before an unpaid invoice escalates, once a year. */
export async function extendPayment(input: { org: string; revision: number }) {
  'use server';
  await planWrite(input.org, '/plan/extension', { key: `extend:${input.revision}` });
  return reload({ revalidate: PLAN_KEYS });
}

/** A Stripe Checkout page where the owner saves the card Tenantly charges; the browser goes there. */
export async function startCardSetup(input: { org: string; returnUrl: string }) {
  'use server';
  const access = await enterTenant(input.org);
  const { url } = await api<{ url: string }>('billing', '/plan/card', {
    token: access.jwt,
    body: { returnUrl: input.returnUrl },
  });
  return respond({ url }, { revalidate: [] });
}

export async function readBillingNotice(input: { org: string; id: number }) {
  'use server';
  const access = await enterTenant(input.org);
  await api('billing', `/plan/notices/${input.id}/read`, { token: access.jwt, body: {} });
  return reload({ revalidate: ['billing'] });
}
