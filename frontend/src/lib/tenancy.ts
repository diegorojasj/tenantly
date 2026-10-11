// Tenant administration RPCs: the shell context, team, locations, policies,
// audit trail and the Tenantly plan. Thin on purpose — each
// call forwards the tenant token to the service that owns the data and that
// service decides; mutations name the query keys they refresh.
import { reload, respond } from '@solidjs/web';
import { GET } from '@solidjs/web/server-functions';

import { enterTenant, forgetTenant } from '../server/access';
import { api } from '../server/api';
import { t } from './i18n';
import type {
  AuditEvent,
  Billing,
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
    viewerId: string;
    seats: number;
  }>('identity', '/tenant/members', { token: access.jwt, query: { scope: access.scopeId } });
});

export const getRoles = GET(async (slug: string) => {
  'use server';
  const access = await enterTenant(slug);
  return api<{ roles: Array<Role>; permissions: Array<[Permission, string]>; canEdit: boolean }>(
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

export async function inviteMember(input: { org: string; email: string; role: RoleId; scopeId: string }) {
  'use server';
  const access = await enterTenant(input.org);
  // The one-time code is returned once, to the inviter, who passes the link on.
  const { invite } = await api<{ invite: string }>('identity', '/tenant/members', {
    token: access.jwt,
    body: { email: input.email, role: input.role, scopeId: input.scopeId },
  });
  return respond({ invite }, { revalidate: ['members', 'audit'] });
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

/** Prices, limits and the estimate come from billing; this only lays them out as meters. */
export const getBilling = GET(async (slug: string): Promise<Billing> => {
  'use server';
  const access = await enterTenant(slug);
  const { customers, payments, ...plan } = await api<
    Omit<Billing, 'meters'> & {
      customers: { used: number; limit: number | null };
      payments: { used: number; limit: number | null };
    }
  >('billing', '/plan', { token: access.jwt });
  return {
    ...plan,
    meters: [
      { id: 'customers', label: t('billing.meterCustomers'), service: t('billing.serviceBilling'), ...customers, unit: t('billing.unitCustomers'), series: [] },
      { id: 'payments', label: t('billing.meterPayments'), service: t('billing.serviceBilling'), ...payments, unit: t('billing.unitPayments'), series: [] },
    ],
  };
});
