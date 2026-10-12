// The Tenantly admin console's RPCs. They work only on the admin host (src/server/host.ts),
// with the admin session cookie, which holds an admin token — never a workspace session.
// Identity checks the admin's access window on every call and forwards billing work to
// billing signed by the admin, so nothing is decided here. A closed window (401) clears
// the session, and the console falls back to its sign-in form.
import { reload, respond } from '@solidjs/web';
import { GET } from '@solidjs/web/server-functions';

import { refuse } from '../server/access';
import { ApiError, adminApi } from '../server/api';
import { onAdminHost } from '../server/host';
import { clearAdminSession, getAdminSession, setAdminSession } from '../server/session';
import { t } from './i18n';
import type {
  AdminAudit,
  AdminOwner,
  AdminOwners,
  AdminPlans,
  AdminPolicy,
  AdminSubscription,
  AdminViewer,
  GrantKind,
  NewBusiness,
  OpenedBusiness,
  OwnerStatus,
  PolicyFields,
  StartingPlan,
} from './types';

async function adminToken(): Promise<string> {
  if (!onAdminHost()) throw Object.assign(refuse(t('admin.wrongHost')), { status: 404 });
  const token = (await getAdminSession())?.token;
  if (!token) throw Object.assign(refuse(t('admin.signInFirst')), { status: 401 });
  return token;
}

/** Every console call: a refused admin token (window closed, blocked) also ends the browser session. */
async function call<T>(path: string, options: { method?: string; body?: unknown; query?: Record<string, string | number | undefined> } = {}) {
  const token = await adminToken();
  try {
    return await adminApi<T>(path, { ...options, token });
  } catch (error) {
    if (error instanceof ApiError && error.status === 401) await clearAdminSession();
    throw error;
  }
}

export const getAdminViewer = GET(async (): Promise<AdminViewer | null> => {
  'use server';
  if (!onAdminHost() || !(await getAdminSession())?.token) return null;
  try {
    return await call<AdminViewer>('/me');
  } catch {
    return null;
  }
});

export async function adminSignIn(input: { email: string; password: string }) {
  'use server';
  if (!onAdminHost()) throw refuse(t('admin.wrongHost'));
  const { token, admin } = await adminApi<{ token: string; admin: AdminViewer }>('/auth/login', { body: input });
  await setAdminSession({ token, activeUntil: admin.activeUntil });
  return reload({ revalidate: ['admin-viewer'] });
}

export async function adminSignOut() {
  'use server';
  await clearAdminSession();
  return reload({ revalidate: ['admin-viewer'] });
}

export const getAdminOwners = GET(async (q: string, offset: number): Promise<AdminOwners> => {
  'use server';
  return call<AdminOwners>('/owners', { query: { q, offset: offset || undefined } });
});

export const getAdminSubscription = GET(async (tenantId: string): Promise<AdminSubscription> => {
  'use server';
  return call<AdminSubscription>(`/businesses/${encodeURIComponent(tenantId)}/subscription`);
});

export const getAdminPlans = GET(async (): Promise<AdminPlans> => {
  'use server';
  return call<AdminPlans>('/plans');
});

export const getAdminPolicy = GET(async (): Promise<AdminPolicy> => {
  'use server';
  return call<AdminPolicy>('/policy');
});

export const getAdminAudit = GET(async (offset: number): Promise<AdminAudit> => {
  'use server';
  return call<AdminAudit>('/audit', { query: { offset: offset || undefined } });
});

const OWNER_KEYS = ['admin-owners', 'admin-audit'];
const SUBSCRIPTION_KEYS = ['admin-owners', 'admin-subscription', 'admin-audit'];

/**
 * The only way an owner gets an account: with their first business and the plan it starts on.
 * The admin sets the first password and hands it over; the owner then creates their team's accounts.
 */
export async function createOwner(input: {
  name: string;
  email: string;
  password: string;
  business: NewBusiness;
  plan: StartingPlan;
  reason: string;
}) {
  'use server';
  const created = await call<AdminOwner & { business: OpenedBusiness }>('/owners', { body: input });
  return respond(created, { revalidate: OWNER_KEYS });
}

/** Another business for an existing owner, on its own subscription. */
export async function addBusiness(input: { userId: string; business: NewBusiness; plan: StartingPlan; reason: string }) {
  'use server';
  const { userId, ...body } = input;
  const opened = await call<OpenedBusiness>(`/owners/${encodeURIComponent(userId)}/businesses`, { body });
  return respond(opened, { revalidate: OWNER_KEYS });
}

/** Active, restricted (read-only) or suspended (signed out, no sign-in); always with a reason. */
export async function setOwnerStatus(input: { userId: string; status: OwnerStatus; reason: string }) {
  'use server';
  const { userId, ...body } = input;
  await call(`/owners/${encodeURIComponent(userId)}/status`, { method: 'PUT', body });
  return reload({ revalidate: OWNER_KEYS });
}

/** Moves a business to a public tier, or to a Custom plan with its own terms; billing prices and audits it. */
export async function assignPlan(input: {
  tenantId: string;
  plan: 'starter' | 'growth' | 'enterprise' | 'custom';
  terms?: { price: string; customerLimit?: number; overagePrice?: string };
  reason: string;
}) {
  'use server';
  const { tenantId, ...body } = input;
  await call(`/businesses/${encodeURIComponent(tenantId)}/plan`, { method: 'PUT', body });
  return reload({ revalidate: SUBSCRIPTION_KEYS });
}

export async function addGrant(input: {
  tenantId: string;
  kind: GrantKind;
  metric?: string;
  value: string;
  days: number;
  reason: string;
}) {
  'use server';
  const { tenantId, ...body } = input;
  await call(`/businesses/${encodeURIComponent(tenantId)}/grants`, { body });
  return reload({ revalidate: SUBSCRIPTION_KEYS });
}

/** Records a transfer (or any payment outside the card) against a Tenantly invoice. */
export async function markInvoicePaid(input: { invoiceId: string; reference: string }) {
  'use server';
  await call(`/invoices/${encodeURIComponent(input.invoiceId)}/paid`, { body: { reference: input.reference } });
  return reload({ revalidate: SUBSCRIPTION_KEYS });
}

/** A plan's new price list: a new version; its businesses move to it at their next renewal. */
export async function repricePlan(input: {
  versionId: string;
  price: string;
  included: number | null;
  overagePrice: string | null;
  cap: string | null;
  reason: string;
}) {
  'use server';
  const { versionId, ...body } = input;
  await call(`/plans/${encodeURIComponent(versionId)}/reprice`, { body });
  return reload({ revalidate: ['admin-plans', 'admin-audit'] });
}

/** The billing policy from now on: a new version, validated by billing. */
export async function editPolicy(input: PolicyFields & { reason: string }) {
  'use server';
  await call('/policy', { method: 'PUT', body: input });
  return reload({ revalidate: ['admin-policy', 'admin-audit'] });
}
