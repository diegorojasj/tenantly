// The tenant boundary, now owned by the identity service. `enterTenant` trades
// the browser's session token for a short-lived tenant token (membership and
// scope proven by identity) plus the shell's context. Every other service
// authorizes with that token, so this module decides nothing on its own: it
// only carries credentials and turns refusals into readable errors.
import 'server-only';

import { markSafeError } from '@solidjs/web';

import type { TenantContext } from '../lib/types';
import { locale, t } from '../lib/i18n';
import { api } from './api';
import { getSession } from './session';

/** A validation failure whose message is written for the user. */
export const refuse = (message: string) => markSafeError(new Error(message));

export async function sessionToken() {
  const token = (await getSession())?.token;
  if (!token) throw Object.assign(refuse(t('common.signInToContinue')), { status: 401 });
  return token;
}

export interface TenantAccess extends TenantContext {
  /** Bearer for operations/billing/identity tenant routes. */
  jwt: string;
  can: (permission: string) => boolean;
}

// Tenant tokens live 5 minutes; reuse one for a short while so a page with
// several reads doesn't pay an identity round trip per read.
const TTL_MS = 60_000;
const cache = new Map<string, { at: number; value: { token: string; context: TenantContext } }>();

export function forgetTenant(slug: string) {
  for (const key of cache.keys()) if (key.includes(`|${slug}|`)) cache.delete(key);
}

export async function enterTenant(slug: string, scope?: string): Promise<TenantAccess> {
  const session = await sessionToken();
  // The token carries the template worded in the viewer's language, so it is cached per language.
  const key = `${session}|${slug}|${scope ?? ''}|${locale()}`;
  const hit = cache.get(key);
  let value = hit && Date.now() - hit.at < TTL_MS ? hit.value : undefined;
  if (!value) {
    value = await api<{ token: string; context: TenantContext }>('identity', `/tenants/${encodeURIComponent(slug)}/token`, {
      token: session,
      body: { scope: scope || null },
    });
    if (cache.size > 500) cache.clear();
    cache.set(key, { at: Date.now(), value });
  }
  const { token, context } = value;
  return { ...context, jwt: token, can: (p) => context.role.permissions.includes(p as never) };
}
